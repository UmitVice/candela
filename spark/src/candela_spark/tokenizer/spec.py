# Qwen2's pre-tokenizer regex: single-digit splitting; llama.cpp knows it as tokenizer.ggml.pre = "qwen2".
SPLIT_PATTERN = r"(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\r\n\p{L}\p{N}]?\p{L}+|\p{N}| ?[^\s\p{L}\p{N}]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+"  # noqa: E501
GGUF_PRE = "qwen2"
VOCAB_SIZE = 32768

PAD, BOS, EOS = "<|pad|>", "<|bos|>", "<|eos|>"
NAMED_SPECIALS = [
    PAD,
    BOS,
    EOS,
    "<|unk|>",
    "<|start_of_turn|>",
    "<|end_of_turn|>",
    "<|system|>",
    "<|user|>",
    "<|assistant|>",
    "<|tool|>",
    "<|tool_call|>",
    "<|/tool_call|>",
    "<|tool_response|>",
    "<|/tool_response|>",
    "<|think|>",
    "<|/think|>",
    "<|fim_prefix|>",
    "<|fim_middle|>",
    "<|fim_suffix|>",
    "<|sep|>",
    "<|mask|>",
    "<|image|>",
    "<|audio|>",
    "<|doc|>",
]
RESERVED_COUNT = 104


def special_tokens() -> list[str]:
    return NAMED_SPECIALS + [f"<|reserved_{i}|>" for i in range(RESERVED_COUNT)]
