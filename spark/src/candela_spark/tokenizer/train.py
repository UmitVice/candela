import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

from tokenizers import Regex, Tokenizer, decoders, models, pre_tokenizers, trainers

from candela_spark import log, paths
from candela_spark.tokenizer import spec

_log = log.get("tokenizer")


def build_empty() -> Tokenizer:
    tok = Tokenizer(models.BPE(byte_fallback=False, unk_token=None))
    tok.pre_tokenizer = pre_tokenizers.Sequence(
        [
            pre_tokenizers.Split(Regex(spec.SPLIT_PATTERN), behavior="isolated", invert=False),
            pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False),
        ]
    )
    tok.decoder = decoders.ByteLevel()
    return tok


def train(texts: Iterator[str], out_dir: Path = paths.TOKENIZER_DIR) -> dict[str, object]:
    tok = build_empty()
    trainer = trainers.BpeTrainer(
        vocab_size=spec.VOCAB_SIZE,
        min_frequency=2,
        special_tokens=spec.special_tokens(),
        initial_alphabet=pre_tokenizers.ByteLevel.alphabet(),
        show_progress=False,
    )
    tok.train_from_iterator(texts, trainer=trainer)
    if tok.get_vocab_size() != spec.VOCAB_SIZE:
        raise RuntimeError(f"vocabulary size {tok.get_vocab_size()} != {spec.VOCAB_SIZE}")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = paths.TOKENIZER_FILE
    tok.save(str(path))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    info = {
        "vocabSize": tok.get_vocab_size(),
        "sha256": digest,
        "specialTokens": len(spec.special_tokens()),
        "bos": tok.token_to_id(spec.BOS),
        "eos": tok.token_to_id(spec.EOS),
        "pad": tok.token_to_id(spec.PAD),
        "pretokenizer": "qwen2-regex+bytelevel",
        "ggufPre": spec.GGUF_PRE,
    }
    paths.TOKENIZER_META.write_text(json.dumps(info, indent=2) + "\n")
    _log.info("tokenizer trained", **info)
    return info


def load(path: Path = paths.TOKENIZER_FILE) -> Tokenizer:
    return Tokenizer.from_file(str(path))


def frozen_hash(path: Path = paths.TOKENIZER_FILE) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
