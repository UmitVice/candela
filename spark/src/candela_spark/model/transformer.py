import math
from dataclasses import dataclass

import mlx.core as mx
import mlx.nn as nn

from candela_spark.model.config import ModelConfig
from candela_spark.model.qat import QATLinear, fake_quant, storage_dtype


class GemmaRMSNorm(nn.Module):
    # Gemma parametrisation: scale = 1 + weight, weight starts at zero; GGUF export stores 1 + weight.
    def __init__(self, dims: int, eps: float) -> None:
        super().__init__()
        self.weight = mx.zeros((dims,), dtype=mx.float32)
        self.eps = eps

    def __call__(self, x: mx.array) -> mx.array:
        return mx.fast.rms_norm(x, (1.0 + self.weight).astype(x.dtype), self.eps)


@dataclass
class AttentionCapture:
    layer: int
    probs: mx.array


class Attention(nn.Module):
    def __init__(self, cfg: ModelConfig, layer: int) -> None:
        super().__init__()
        d, hd = cfg.hidden_size, cfg.head_dim
        std = cfg.init_std_scale / math.sqrt(d)
        self.n_heads, self.n_kv, self.head_dim = cfg.num_heads, cfg.num_kv_heads, hd
        self.q_proj = QATLinear(d, cfg.num_heads * hd, std, cfg.quant)
        self.k_proj = QATLinear(d, cfg.num_kv_heads * hd, std, cfg.quant)
        self.v_proj = QATLinear(d, cfg.num_kv_heads * hd, std, cfg.quant)
        self.o_proj = QATLinear(
            cfg.num_heads * hd, d, cfg.init_std_scale / math.sqrt(cfg.num_heads * hd), cfg.quant
        )
        self.q_norm = GemmaRMSNorm(hd, cfg.norm_eps)
        self.k_norm = GemmaRMSNorm(hd, cfg.norm_eps)
        self.is_global = cfg.is_global(layer)
        self.rope_base = cfg.rope_global_base if self.is_global else cfg.rope_local_base
        self.window = cfg.sliding_window
        self.scale = 1.0 / math.sqrt(hd)

    def __call__(
        self,
        x: mx.array,
        mask: mx.array | str,
        offset: int = 0,
        cache: list[mx.array] | None = None,
        capture: bool = False,
    ) -> tuple[mx.array, mx.array | None]:
        b, t, _ = x.shape
        q = self.q_proj(x).reshape(b, t, self.n_heads, self.head_dim).transpose(0, 2, 1, 3)
        k = self.k_proj(x).reshape(b, t, self.n_kv, self.head_dim).transpose(0, 2, 1, 3)
        v = self.v_proj(x).reshape(b, t, self.n_kv, self.head_dim).transpose(0, 2, 1, 3)
        q = mx.fast.rope(
            self.q_norm(q), self.head_dim, traditional=False, base=self.rope_base, scale=1.0, offset=offset
        )
        k = mx.fast.rope(
            self.k_norm(k), self.head_dim, traditional=False, base=self.rope_base, scale=1.0, offset=offset
        )
        if cache is not None:
            if cache:
                k = mx.concatenate([cache[0], k], axis=2)
                v = mx.concatenate([cache[1], v], axis=2)
            cache[:] = [k, v]
        probs = None
        if capture:
            rep = self.n_heads // self.n_kv
            kk = mx.repeat(k, rep, axis=1).astype(mx.float32)
            scores = (q.astype(mx.float32) @ kk.transpose(0, 1, 3, 2)) * self.scale
            if isinstance(mask, mx.array):
                scores = mx.where(mask, scores, -mx.inf)
            probs = mx.softmax(scores, axis=-1)
        out = mx.fast.scaled_dot_product_attention(q, k, v, scale=self.scale, mask=mask)
        out = out.transpose(0, 2, 1, 3).reshape(b, t, -1)
        return self.o_proj(out), probs


class FeedForward(nn.Module):
    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__()
        d, f = cfg.hidden_size, cfg.intermediate_size
        self.gate_proj = QATLinear(d, f, cfg.init_std_scale / math.sqrt(d), cfg.quant)
        self.up_proj = QATLinear(d, f, cfg.init_std_scale / math.sqrt(d), cfg.quant)
        self.down_proj = QATLinear(f, d, cfg.init_std_scale / math.sqrt(f), cfg.quant)

    def __call__(self, x: mx.array) -> mx.array:
        return self.down_proj(nn.gelu_approx(self.gate_proj(x)) * self.up_proj(x))


class Block(nn.Module):
    def __init__(self, cfg: ModelConfig, layer: int) -> None:
        super().__init__()
        self.input_layernorm = GemmaRMSNorm(cfg.hidden_size, cfg.norm_eps)
        self.self_attn = Attention(cfg, layer)
        self.post_attention_layernorm = GemmaRMSNorm(cfg.hidden_size, cfg.norm_eps)
        self.pre_feedforward_layernorm = GemmaRMSNorm(cfg.hidden_size, cfg.norm_eps)
        self.mlp = FeedForward(cfg)
        self.post_feedforward_layernorm = GemmaRMSNorm(cfg.hidden_size, cfg.norm_eps)

    def __call__(
        self,
        x: mx.array,
        mask: mx.array | str,
        offset: int = 0,
        cache: list[mx.array] | None = None,
        capture: bool = False,
    ) -> tuple[mx.array, mx.array | None]:
        h, probs = self.self_attn(self.input_layernorm(x), mask, offset, cache, capture)
        x = x + self.post_attention_layernorm(h)
        x = x + self.post_feedforward_layernorm(self.mlp(self.pre_feedforward_layernorm(x)))
        return x, probs


def local_mask(t_q: int, t_kv: int, window: int, offset: int = 0) -> mx.array:
    qi = mx.arange(offset, offset + t_q)[:, None]
    ki = mx.arange(t_kv)[None, :]
    return (ki <= qi) & (ki > qi - window)


def causal_mask(t_q: int, t_kv: int, offset: int = 0) -> mx.array:
    qi = mx.arange(offset, offset + t_q)[:, None]
    ki = mx.arange(t_kv)[None, :]
    return ki <= qi


class SparkLM(nn.Module):
    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self.embed_tokens = mx.random.normal(
            (cfg.vocab_size, cfg.hidden_size), scale=1.0 / math.sqrt(cfg.hidden_size), dtype=mx.float32
        )
        self.layers = [Block(cfg, i) for i in range(cfg.num_layers)]
        self.norm = GemmaRMSNorm(cfg.hidden_size, cfg.norm_eps)
        self.qat = True

    def set_qat(self, enabled: bool) -> None:
        self.qat = enabled
        for _, m in self.named_modules():
            if isinstance(m, QATLinear):
                m.qat = enabled

    def embedding_matrix(self) -> mx.array:
        if self.qat and self.cfg.quant.quantize_embedding:
            return fake_quant(self.embed_tokens, self.cfg.quant)
        return self.embed_tokens.astype(storage_dtype(self.cfg.quant))

    def hidden(
        self,
        tokens: mx.array,
        caches: list[list[mx.array]] | None = None,
        capture: bool = False,
    ) -> tuple[mx.array, list[mx.array]]:
        cfg = self.cfg
        x = self.embed(tokens)
        t = tokens.shape[1]
        offset = caches[0][0].shape[2] if caches and caches[0] else 0
        t_kv = offset + t
        if offset == 0 and not capture:
            global_mask: mx.array | str = "causal"
        else:
            global_mask = causal_mask(t, t_kv, offset)
        lmask = local_mask(t, t_kv, cfg.sliding_window, offset)
        captured: list[mx.array] = []
        for i, layer in enumerate(self.layers):
            mask = global_mask if layer.self_attn.is_global else lmask
            x, probs = layer(x, mask, offset, caches[i] if caches is not None else None, capture)
            if probs is not None:
                captured.append(probs)
        return self.norm(x), captured

    def embed(self, tokens: mx.array) -> mx.array:
        emb = self.embedding_matrix()
        return emb[tokens] * mx.array(math.sqrt(self.cfg.hidden_size), dtype=emb.dtype)

    def head(self, h: mx.array) -> mx.array:
        return h @ self.embedding_matrix().T

    def __call__(self, tokens: mx.array, caches: list[list[mx.array]] | None = None) -> mx.array:
        h, _ = self.hidden(tokens, caches)
        logits = self.head(h)
        if self.cfg.output_mult != 1.0:
            logits = logits * self.cfg.output_mult
        return logits
