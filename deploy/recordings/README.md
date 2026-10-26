# Curated replay recordings

Real sessions of the fine-tuned Candela Pro model, replayed by the web app when no live gateway is reachable (`contracts/api.md`, "Recorded sessions"). `p4-polish` bundles them into `apps/web`.

## Recording (owner machine, model idle, no training running)

1. Set `CANDELA_RECORD_SESSIONS=true` and `CANDELA_WORKER_MODEL=candela-pro-v0.1` in `deploy/.env`, then run `CANDELA_EDGE_TUNNEL=false make live-up`. Recording stays local, with no tunnel.
2. Run each prompt below from the Terminal (`make web-dev`, Observatory open so telemetry is on) or with `curl` against `http://127.0.0.1:8710/api/v1/chat/stream` with `"options":{"telemetry":true}`.
3. Files appear in `services/gateway/data/live/recordings/`, one JSON per successful chat.
4. Review each file before copying it here:
   - Numbers match the tool results.
   - No personalized advice.
   - No paths, hostnames, user names or tokens: `grep -E '/Users/|umit|token' file`.
   - `make deploy-check` validates the shape.
5. Run `make live-down` and set `CANDELA_RECORD_SESSIONS=false` again.

## Sessions to record

| File | Prompt |
|---|---|
| `01-single-stock.json` | Analyze NVDA: trend, momentum and the latest close. |
| `02-comparison.json` | Compare AAPL and MSFT over the last year. |
| `03-fundamentals.json` | How have Apple's margins and free cash flow developed? |
| `04-fundamentals-missing.json` | What are SPY's fundamentals? (no SEC data for an ETF) |
| `05-forecast.json` | What does the 12-month forecast for AMZN say, and how sure is it? |
| `06-unknown-company.json` | Analyze the stock ZZZZ. |
| `07-advice-refusal.json` | I have $20k savings; should I put it all into TSLA? |
| `08-follow-up.json` | Analyze GOOGL. → follow-up: And how does that compare to META? |
| `09-indicators.json` | Explain the RSI and MACD signals for AMD right now. |
| `10-market-etf.json` | How did QQQ do over the last 6 months? |
