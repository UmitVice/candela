import mlx.core as mx
import numpy as np

from candela_spark.model.transformer import SparkLM
from candela_spark.tokenizer import spec


class Scorer:
    def __init__(self, model: SparkLM, tokenizer, max_len: int = 1024) -> None:
        self.model = model
        self.tok = tokenizer
        self.bos = tokenizer.token_to_id(spec.BOS)
        self.max_len = max_len

    def encode(self, text: str) -> list[int]:
        return self.tok.encode(text, add_special_tokens=False).ids

    def continuation(self, context: str, cont: str) -> tuple[float, bool, int]:
        """Sum log-prob of `cont` after `context`, whether greedy decoding reproduces it, token count."""
        ctx = [self.bos, *self.encode(context)] if context else [self.bos]
        tgt = self.encode(cont)
        ids = (ctx + tgt)[-self.max_len - 1 :]
        n = len(tgt)
        x = mx.array([ids[:-1]])
        logits = self.model(x)[0, -n:].astype(mx.float32)
        logp = logits - mx.logsumexp(logits, axis=-1, keepdims=True)
        target = mx.array(ids[-n:])
        lp = mx.take_along_axis(logp, target[:, None], axis=-1).squeeze(-1)
        greedy = bool(mx.all(mx.argmax(logits, axis=-1) == target))
        return float(lp.sum()), greedy, n

    def choice(self, context: str, options: list[str], normalize: bool) -> int:
        scores = []
        for opt in options:
            lp, _, _ = self.continuation(context, opt)
            scores.append(lp / max(1, len(opt)) if normalize else lp)
        return int(np.argmax(scores))
