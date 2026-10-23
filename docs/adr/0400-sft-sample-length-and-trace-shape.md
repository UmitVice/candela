# 0400 — SFT sample length cap of 4 096 tokens and lighter analysis traces

- Status: accepted
- Date: 2026-10-23

## Context

The master plan caps supervised samples at 2 048 tokens. Measured with the Gemma 4 chat template on 200 traces generated through the real gateway (`p1-ml`), the system prompt plus the six tool declarations already take 787 tokens, and the model views are long because the tokenizer splits numbers finely: `get_fundamentals` ≈ 720 tokens (limit 4), `get_price_history` ≈ 525, `get_technical_indicators` ≈ 330, `get_forecast` ≈ 190, `get_quote` ≈ 125. A full "Analyze X" answer turn is ≈ 4 000 tokens. At 2 048 only 64 % of trace turns survive, and nearly every full analysis and comparison — the core Candela behaviour — would be dropped.

## Decision

- Dataset `d0.1` keeps samples up to **4 096 tokens** (`maxTokens: 4096` in `ml/configs/data/d0.1.yaml`); training uses `maxSeqLength: 4096` when the probe shows the peak stays ≤ 9 GB, otherwise 2 048 with a note in ADR 0003.
- Analysis and comparison traces call `get_fundamentals` with `limit: 2` (the composer only uses the newest period and the ratios), which the tool schema allows and which a well-behaved model should also prefer.
- The 2 048-token probes required by the brief still run, plus one probe at 4 096, so both numbers are on record.

## Consequences

- Activation memory per step roughly doubles for the longest samples; gradient checkpointing and the supervised-positions-only LM head keep it bounded, and the probe measures it.
- Follow-up turns whose full history exceeds 4 096 tokens are still dropped (their first turns remain).

## Alternatives considered

- Keep 2 048: loses most grounded analyses, the behaviour the release gate measures.
- Shrink model views: they are a gateway contract (`contracts/tools.md`) and must match production byte for byte.
- Truncate old tool messages: the model would learn to answer from views it cannot see.
