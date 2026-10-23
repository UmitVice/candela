from pathlib import Path

import mlx.core as mx

from candela_spark.model.config import ModelConfig
from candela_spark.model.transformer import SparkLM
from candela_spark.tokenizer import spec
from candela_spark.tokenizer.train import load as load_tokenizer
from candela_spark.train import checkpoint


def load_from_checkpoint(ckpt: Path) -> SparkLM:
    params, _, state = checkpoint.load(ckpt)
    model = SparkLM(ModelConfig.from_dict(state["modelConfig"]))
    model.load_weights(list(params.items()), strict=True)
    mx.eval(model.parameters())
    return model


def generate(
    model: SparkLM,
    prompt: str,
    max_new_tokens: int = 80,
    temperature: float = 0.8,
    top_p: float = 0.95,
    seed: int = 0,
    qat: bool = True,
) -> str:
    tok = load_tokenizer()
    model.set_qat(qat)
    ids = [tok.token_to_id(spec.BOS), *tok.encode(prompt, add_special_tokens=False).ids]
    eos = tok.token_to_id(spec.EOS)
    key = mx.random.key(seed)
    caches: list[list[mx.array]] = [[] for _ in model.layers]
    x = mx.array([ids])
    out: list[int] = []
    for _ in range(max_new_tokens):
        logits = model(x, caches)[0, -1].astype(mx.float32)
        if temperature <= 0:
            nxt = int(mx.argmax(logits))
        else:
            probs = mx.softmax(logits / temperature)
            order = mx.argsort(-probs)
            sorted_p = probs[order]
            cum = mx.cumsum(sorted_p)
            keep = (cum - sorted_p) < top_p
            filtered = mx.where(keep, sorted_p, 0.0)
            key, sub = mx.random.split(key)
            choice = int(mx.random.categorical(mx.log(filtered + 1e-20), key=sub))
            nxt = int(order[choice])
        if nxt == eos:
            break
        out.append(nxt)
        x = mx.array([[nxt]])
    return tok.decode(out)
