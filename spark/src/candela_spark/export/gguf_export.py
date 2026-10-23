import json
from pathlib import Path
from typing import Any

import gguf
import mlx.core as mx
import numpy as np

from candela_spark import paths
from candela_spark.model.config import ModelConfig
from candela_spark.tokenizer import spec

_LINEAR_NAMES = {
    "self_attn.q_proj": "attn_q",
    "self_attn.k_proj": "attn_k",
    "self_attn.v_proj": "attn_v",
    "self_attn.o_proj": "attn_output",
    "mlp.gate_proj": "ffn_gate",
    "mlp.up_proj": "ffn_up",
    "mlp.down_proj": "ffn_down",
}
_NORM_NAMES = {
    "input_layernorm": "attn_norm",
    "post_attention_layernorm": "post_attention_norm",
    "pre_feedforward_layernorm": "ffn_norm",
    "post_feedforward_layernorm": "post_ffw_norm",
    "self_attn.q_norm": "attn_q_norm",
    "self_attn.k_norm": "attn_k_norm",
}


def _np(a: mx.array) -> np.ndarray:
    return np.asarray(a.astype(mx.float32)) if a.dtype == mx.bfloat16 else np.asarray(a)


def q4_1_blocks(packed: mx.array, scales: mx.array, biases: mx.array) -> tuple[np.ndarray, float]:
    """Repack MLX affine int4 (8 nibbles per uint32, low nibble first) into ggml Q4_1 blocks of 32:
    {fp16 d, fp16 m, 16 bytes where byte j holds q[j] | q[j + 16] << 4}. Same formula: no requantisation."""
    p = np.asarray(packed).astype(np.uint32)
    rows = p.shape[0]
    shifts = np.arange(8, dtype=np.uint32) * 4
    q = ((p[..., None] >> shifts) & 0xF).astype(np.uint8).reshape(rows, -1, 32)
    s32 = _np(scales).astype(np.float32)
    b32 = _np(biases).astype(np.float32)
    d16, m16 = s32.astype(np.float16), b32.astype(np.float16)
    deviation = float(
        max(np.abs(d16.astype(np.float32) - s32).max(), np.abs(m16.astype(np.float32) - b32).max())
    )
    qs = (q[..., :16] | (q[..., 16:] << 4)).astype(np.uint8)
    blocks = np.concatenate([d16[..., None].view(np.uint8), m16[..., None].view(np.uint8), qs], axis=-1)
    return blocks.reshape(rows, -1), deviation


def _tokenizer(writer: gguf.GGUFWriter) -> None:
    tok = json.loads(paths.TOKENIZER_FILE.read_text())
    vocab: dict[str, int] = tok["model"]["vocab"]
    added = {t["content"]: t["id"] for t in tok["added_tokens"]}
    size = max([*vocab.values(), *added.values()]) + 1
    tokens = [""] * size
    types = [gguf.TokenType.NORMAL] * size
    for t, i in vocab.items():
        tokens[i] = t
    for t, i in added.items():
        tokens[i] = t
        types[i] = gguf.TokenType.CONTROL
    merges = [m if isinstance(m, str) else " ".join(m) for m in tok["model"]["merges"]]
    writer.add_tokenizer_model("gpt2")
    writer.add_tokenizer_pre(spec.GGUF_PRE)
    writer.add_token_list(tokens)
    writer.add_token_types(types)
    writer.add_token_merges(merges)
    writer.add_bos_token_id(added[spec.BOS])
    writer.add_eos_token_id(added[spec.EOS])
    writer.add_pad_token_id(added[spec.PAD])
    writer.add_add_bos_token(True)
    writer.add_add_eos_token(False)


def write_gguf(q: dict[str, mx.array], cfg: ModelConfig, out: Path, name: str) -> dict[str, Any]:
    if cfg.output_mult != 1.0:
        raise ValueError("gemma3 GGUF needs output_mult == 1 (fold or untie first)")
    arch = "gemma3"
    writer = gguf.GGUFWriter(str(out), arch)
    writer.add_name(name)
    writer.add_context_length(cfg.max_seq_len)
    writer.add_embedding_length(cfg.hidden_size)
    writer.add_block_count(cfg.num_layers)
    writer.add_feed_forward_length(cfg.intermediate_size)
    writer.add_head_count(cfg.num_heads)
    writer.add_head_count_kv(cfg.num_kv_heads)
    writer.add_key_length(cfg.head_dim)
    writer.add_value_length(cfg.head_dim)
    writer.add_layer_norm_rms_eps(cfg.norm_eps)
    writer.add_rope_freq_base(cfg.rope_global_base)
    writer.add_rope_freq_base_swa(cfg.rope_local_base)
    writer.add_sliding_window(cfg.sliding_window)
    writer.add_file_type(gguf.LlamaFileType.MOSTLY_Q4_1)
    writer.add_quantization_version(gguf.GGML_QUANT_VERSION)
    _tokenizer(writer)
    max_dev = 0.0

    def add_q(gname: str, key: str) -> None:
        nonlocal max_dev
        blocks, dev = q4_1_blocks(q[f"{key}.weight"], q[f"{key}.scales"], q[f"{key}.biases"])
        max_dev = max(max_dev, dev)
        writer.add_tensor(gname, blocks, raw_dtype=gguf.GGMLQuantizationType.Q4_1)

    add_q("token_embd.weight", "embed_tokens")
    for i in range(cfg.num_layers):
        for src, dst in _LINEAR_NAMES.items():
            add_q(f"blk.{i}.{dst}.weight", f"layers.{i}.{src}")
        for src, dst in _NORM_NAMES.items():
            w = _np(q[f"layers.{i}.{src}.weight"]).astype(np.float32) + 1.0
            writer.add_tensor(f"blk.{i}.{dst}.weight", w)
    writer.add_tensor("output_norm.weight", _np(q["norm.weight"]).astype(np.float32) + 1.0)
    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_tensors_to_file()
    writer.close()
    return {
        "path": out.name,
        "bytes": out.stat().st_size,
        "type": "Q4_1",
        "arch": arch,
        "maxScaleBiasFp16Deviation": max_dev,
    }
