# 0007 — Market data sources

- Status: accepted
- Date: 2026-10-23

## Context

The model must ground every number in tool outputs, so the gateway needs daily prices, fundamentals and forecasts for US equities without paid plans or new accounts. Probing on 2026-10-23 showed: Stooq's CSV endpoint now serves a JavaScript proof-of-work bot challenge (circumventing it is not acceptable); SEC EDGAR rejects requests whose User-Agent lacks a contact email (403); the Nasdaq Trader symbol directory is openly downloadable.

## Decision

- Symbols: Nasdaq Trader directory files.
- Prices: an offline **snapshot** built from a permissively licensed public dataset on Hugging Face, shipped as a read-only SQLite file and always labelled with its `asOf` date.
- Fundamentals: SEC company facts, enabled only when the owner configures `SEC_USER_AGENT` with their contact details; otherwise the tool reports `data_unavailable`, a case the model is trained to handle.
- Forecasts: a clearly labelled statistical baseline (block bootstrap) until Vaniras data is connected.
- Vaniras (the owner's platform: forecasts with P10/P50/P90 bands, scores, fundamentals for ~1 000 US stocks) is the intended primary source; its adapter is part of a later phase once the owner provides an export or API.
- Optional keyed end-of-day provider behind the same interface.

## Consequences

- The public demo is honest about data freshness; analyses cite `asOf` and `source`.
- Swapping in Vaniras or a keyed provider is configuration plus one adapter, with no model retraining because tool result shapes are fixed by `contracts/tools.md`.

## Alternatives considered

- Scraping Yahoo Finance or similar unofficial endpoints: terms of service and reliability risks for a public project.
- Paid or keyed APIs: require owner sign-up; supported later through the `live` adapter.
