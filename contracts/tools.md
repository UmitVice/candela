# LLM tools — results contract

`contracts/tools.json` holds the function schemas sent to the model (OpenAI `tools` format). This file fixes what each tool returns. Every tool produces two views:

- **Model view**: compact JSON string placed in the `tool` message the model reads. Training data (`ml/`) must emit exactly these shapes, key order included, so the fine-tuned model sees at inference what it saw in training.
- **UI view** (`tool_result.data` in the chat stream): richer payload for rendering (charts, tables). Never sent to the model.

Rules for model views

- Minified JSON, keys in the order shown, numbers rounded (prices 2 dp, percentages 2 dp, ratios 3 dp, large values as integers).
- Always include `asOf` and `source` so answers can cite freshness.
- Failures: `{"error":"<code>","message":"<short text>"}` with codes `not_found`, `data_unavailable`, `invalid_arguments`.
- Hard cap 2 500 characters; trim arrays from the oldest side first.

## search_symbols

Model view: `{"query":"nvidia","results":[{"symbol":"NVDA","name":"NVIDIA Corporation","exchange":"NASDAQ"}]}`
UI view: `{ kind: 'symbols', results: [...] }`

## get_quote

Model view:
```json
{"symbol":"NVDA","name":"NVIDIA Corporation","asOf":"2026-10-22","close":182.41,"changePct":-1.32,"open":184.9,"high":185.2,"low":181.75,"volume":201345678,"fiftyTwoWeekHigh":212.3,"fiftyTwoWeekLow":118.6,"avgVolume30d":187650432,"source":"snapshot","delayed":true}
```
UI view: `{ kind: 'quote', quote: Quote }`

## get_price_history

Model view:
```json
{"symbol":"NVDA","range":"6M","asOf":"2026-10-22","start":{"t":"2026-04-22","c":141.2},"end":{"t":"2026-10-22","c":182.41},"returnPct":29.19,"high":{"t":"2026-09-30","h":212.3},"low":{"t":"2026-04-25","l":138.9},"volatilityAnnualizedPct":41.7,"maxDrawdownPct":-18.42,"avgVolume":195230111,"weeklyCloses":[141.2,145.8,150.1],"source":"snapshot"}
```
`weeklyCloses` = last close of each ISO week, oldest first, at most 60 values (use monthly closes for 2Y and 5Y, key `monthlyCloses`).
UI view: `{ kind: 'price_history', history: PriceHistory }`

## get_technical_indicators

Model view:
```json
{"symbol":"NVDA","asOf":"2026-10-22","close":182.41,"sma20":190.12,"sma50":184.55,"sma200":160.31,"ema12":187.02,"ema26":188.64,"rsi14":41.8,"macd":-1.62,"macdSignal":0.35,"macdHist":-1.97,"bbUpper":204.9,"bbMiddle":190.12,"bbLower":175.34,"bbPercentB":0.24,"atr14":6.12,"atrPct":3.36,"signals":[{"id":"price_below_sma50","tone":"bearish","detail":"Close 182.41 is 1.16% below SMA50 184.55"},{"id":"golden_cross_active","tone":"bullish","detail":"SMA50 above SMA200 since 2026-05-14"}],"source":"snapshot"}
```
Signal ids (closed set): `rsi_overbought` (>70), `rsi_oversold` (<30), `price_above_sma50`, `price_below_sma50`, `price_above_sma200`, `price_below_sma200`, `golden_cross_recent` (within 20 sessions), `death_cross_recent`, `golden_cross_active`, `death_cross_active`, `macd_bullish_cross` (within 5 sessions), `macd_bearish_cross`, `bb_upper_break`, `bb_lower_break`, `high_volatility` (ATR% > 4).
UI view: `{ kind: 'indicators', indicators: IndicatorSet, history: PriceHistory }`

## get_fundamentals

Model view:
```json
{"symbol":"AAPL","name":"Apple Inc.","period":"annual","currency":"USD","periods":[{"fy":2025,"fp":"FY","end":"2025-09-27","revenue":416161000000,"grossProfit":195201000000,"operatingIncome":133050000000,"netIncome":112010000000,"epsDiluted":7.46,"operatingCashFlow":111482000000,"freeCashFlow":98767000000,"totalAssets":359241000000,"totalLiabilities":285508000000,"cash":35934000000,"longTermDebt":78328000000}],"ratios":{"grossMarginPct":46.91,"operatingMarginPct":31.97,"netMarginPct":26.92,"fcfMarginPct":23.73,"revenueGrowthPct":6.43,"epsGrowthPct":22.7,"debtToAssets":0.218},"source":"sec","asOf":"2025-10-31"}
```
Missing values are omitted, never `null`. Ratios use the newest period; growth compares it with the same period one year earlier.
UI view: `{ kind: 'fundamentals', fundamentals: Fundamentals }`

## get_forecast

Model view:
```json
{"symbol":"NVDA","asOf":"2026-10-22","basePrice":182.41,"source":"baseline","method":"block bootstrap of 5y daily log returns","horizons":[{"m":3,"p10":151.2,"p50":186.0,"p90":224.9},{"m":6,"p10":139.5,"p50":189.7,"p90":251.3},{"m":9,"p10":131.8,"p50":193.4,"p90":274.6},{"m":12,"p10":125.0,"p50":197.2,"p90":297.1}]}
```
UI view: `{ kind: 'forecast', forecast: Forecast }`

## System prompt (owned by the gateway, mirrored in training data)

Stored at `contracts/system-prompt.md`. Training examples must use it verbatim (with the `{{today}}` placeholder rendered) so the fine-tuned model is conditioned on the production prompt.
