# 0401 — Train Candela Pro v0.1 at 2 048 tokens; quick-analysis traces carry the sectioned answer

- Status: accepted
- Date: 2026-10-24

## Context

ADR 0400 kept `d0.1` samples up to 4 096 tokens so `p2-train` could pick 2 048 or 3 072 tokens. `p2-train` measured both on the same machine (Apple M5 Pro, 24 GB, QAT int4 base, LoRA rank 16 on layers 32–47, gradient checkpointing, 64-position LM-head chunks):

| Window | Peak memory | Tokens/s (longest samples) |
|---|---|---|
| 2 048 (ADR 0003 probe) | 10.46 GB | 332 |
| 3 072 (`probe-l16-3k`, 20 steps on the 1 091 longest samples) | 11.99 GB | 187 |

Token counts of the 6 000 gateway-executed traces (Gemma tokenizer): full analysis answers have a median of 3 412 tokens (93 % above 3 072), comparison answers 3 535, follow-ups after an analysis 3 933. A 3 072 window therefore buys almost none of the long answers it was meant for, while it costs 1.5 GB more than the 10.5 GB budget (above the 11 GB start threshold of the owner's guard policy) and runs at about half the throughput.

## Decision

- Candela Pro v0.1 trains at **`maxSeqLength` 2 048**. Dataset `d0.2` applies the window at build time (`maxTokens: 2048`), so bucket quotas are filled with samples that are actually trained.
- The traces gain a **`quick_analysis` intent** (10 % of conversations: "Quick take on X", "TL;DR on X", …) that calls `get_quote`, `get_technical_indicators` and `get_forecast` and answers with the same sectioned, grounded format as a full analysis (Snapshot, Trend & Momentum, Outlook & Risks, Bottom line, source line). These samples fit 2 048 tokens and teach the analysis answer shape; full analyses and comparisons still train their tool-call turns, and their long final answers rely on what the model learns from the shorter sectioned answers.
- The tool contracts and model views are unchanged (they must match production byte for byte).

## Consequences

- No supervised example of a complete five-tool analysis answer is trained in v0.1. The held-out `tool_use` suite still contains full analyses, so grounding on them is measured, not assumed.
- Training stays inside the 10.5 GB budget and the 11 GB start threshold.

## Alternatives considered

- 3 072 tokens with lighter analyses (`range: 6M`, `limit: 1`): would bring analyses to ≈ 3 050 tokens, at the edge of the window, at 12 GB peak and half the throughput.
- Detached prompt KV (train only on completion positions against a frozen prompt cache): would cut activation memory to the answer length, but is a deep change to the Gemma 4 attention path (sliding-window and global layers) with a gradient approximation; deferred.
