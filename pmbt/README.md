# Testing framework: killing bad strategies without real money

Goal: **falsify** strategies cheaply. A strategy survives only if it makes money **after
today's fees, with realistic latency and fills, out-of-sample**. Code lives in `pmbt/`.
Each strategy test lives in `research/<idea_id>_<name>/` and writes `result.json` plus `README.md`.

## 1. Data layers

| Layer | Source | What it is | Used for |
|---|---|---|---|
| Market metadata | `SII-WANGZJ/Polymarket_data/markets.parquet` (4.05M markets) → `data/derived/markets.parquet` | question, event, created/end dates, neg_risk, **parsed outcome** (`yes_won`), heuristic **category** (`pmbt.fees.classify`) | all |
| Trade tape | `SII-WANGZJ/Polymarket_data/trades.parquet` (1.27B fills, 2022-11 → 2026-10-04, on-chain, includes V2) → `data/derived/tape/month=*/` | YES-normalized fills: `ts, mkt, p, usd, sh, tb` | all historical tests |
| Hourly bars | built from the tape → `data/derived/bars_1h.parquet` | per market-hour VWAP, first/last, taker-buy VWAP (≈ask), taker-sell VWAP (≈bid) | horizon snapshots, event studies |
| Crypto up/down books | `kachoio/...` (1 Hz top-of-book, 89k 5-min windows, Mar–May 2026), `aliplayer1/polymarket-crypto-updown` (BBO events, trades, Binance and Chainlink spot) | real order books | ideas 1, 19, 21, 31, 33, 34 |
| Spot crypto | Coinbase 1m candles API, `data.binance.vision` dumps | reference prices | 21, 22 |
| External fair value | football-data.co.uk (Pinnacle odds), Open-Meteo historical forecasts, FRED | models | 20, 23, 24 |
| **Live recordings** | our own recorder on the CLOB WebSocket and REST, plus Kalshi REST | full L2 books of many markets, simultaneously | 1, 2, 3, 4, 29, 30 (forward tests) |

Wallet-level data (`maker` / `taker` addresses) is queried straight from HF with DuckDB
(`pmbt.db.HF_TRADES`) when needed (ideas 36–38).

## 2. Execution realism rules (non-negotiable)

1. **Fees.** Always apply the *current* fee schedule (`pmbt/fees.py`) to every simulated taker fill,
   even when the historical trade happened before fees existed. Makers pay 0. A maker rebate is
   only credited when we can estimate our share of the fee pool, never as 100%.
2. **Latency.** Decisions use information available at time `t`. Orders execute no earlier than
   `t + latency`:
   * default 2 s for tape-based tests (tape resolution is 1 s),
   * 150 ms taker speed bump + 100–300 ms network for crypto book replays,
   * stress test at 2× and 5× the latency.
3. **Taker fills (tape).** Use the *first real taker print on the same side* after `t + latency`
   (`pmbt.tape.taker_entries`). That is a price someone actually paid, which approximates the ask.
   Never use mid or last trade as an entry price. Size is capped at 25% of the same-side volume
   printed within 10 minutes at no worse than first price + 1¢.
4. **Taker fills (books).** Walk the recorded book at `t + latency`. Where only top of book exists,
   cap size at the displayed best size.
5. **Maker fills.** A resting order fills only when a later opposite-side taker print trades
   **strictly through** our price (we are assumed to be last in the queue). Fill size is ≤ the
   print size × queue share (default 0.5). Adverse selection is then measured, not assumed away.
6. **Settlement.** Hold to resolution unless the strategy defines an exit. Winners pay $1. A 50/50
   resolution pays $0.50. Markets without a clean outcome are excluded *before* the test (and the
   exclusion rate is reported). Capital is locked from entry until `last trade ts` (a proxy for
   the resolution time), which matters for annualized returns.
7. **No look-ahead.** Market selection may only use info known at `t`: question text, created
   date, `end_ts` (caveat: end dates are sometimes edited; we use the final value and flag it),
   the past tape. Never filter on the final volume, outcome or resolution time.
8. **Capacity.** Report the $ deployable per day at the measured edge, not just ROI.

## 3. Statistics

* Unit of independence = **event** (`event_id`). Markets in one event, such as neg-risk
  candidates or ladder strikes, are correlated, so all CIs use an **event-clustered bootstrap**
  (`pmbt.metrics.summarize`).
* **Time split:** in-sample = before 2026-04-01, out-of-sample (OOS) = 2026-04-01 → 2026-10-04.
  Parameters may only be tuned in-sample. For datasets that span only a few months (crypto
  books), use the first 60% / last 40% chronologically.
* **Multiple testing:** across 40 ideas × several variants, require one-sided p < 0.01 OOS (not
  0.05) and the same sign in-sample.
* Stress tests: 2× fees, 2× latency, +1¢ slippage. Report whether the edge survives.

## 4. Verdict ladder

| Verdict | Rule |
|---|---|
| **KILL** | OOS ROI ≤ 0 after fees, or the edge vanishes under modest stress (+1¢ or 2× latency), or the logic is broken at desk-check. |
| **WEAK** | OOS ROI > 0 but p > 0.01, or OOS and in-sample disagree. |
| **PROMISING** | OOS ROI > 0, p < 0.01, same sign in-sample, survives stress. Then it moves to live paper trading. |
| **INCONCLUSIVE** | Not enough data. It needs forward live recording. |

## 5. Forward testing (live, no money)

For ideas with no historical books (complement arb, neg-risk arb, cross-venue arb, MM,
reward farming) we run `research/live/recorder.py`. It subscribes to the public CLOB market
WebSocket for a broad set of active markets and stores L2 book snapshots and trades. We also poll
Kalshi. Strategies are then simulated on that recording with the same fill rules. The step after
that (not done here) would be paper trading the survivors in real time with real order-placement
latency, and then tiny real size.

## 6. Result file schema (`research/<id>/result.json`)

```json
{"idea": 8, "name": "...", "variants": [ {summary from pmbt.metrics.summarize, "params": {...}} ],
 "best_variant_chosen_in_sample": "...", "verdict": "KILL|WEAK|PROMISING|INCONCLUSIVE",
 "notes": "assumptions, caveats, data issues"}
```

## 7. Known limitations (assessment after phase 1, 2026-10-17)
* **Reused out-of-sample data.** All 40 ideas, with up to ~2,000 variants per grid, were scored on the
  same Apr–Oct 2026 OOS window, and researchers saw OOS results of non-chosen variants. That window
  effectively served as validation, not as an untouched test set. Post-hoc leads (e.g. "mentions")
  are hypotheses only.
* **One OOS regime** (6 months). There was no walk-forward over several periods, only per-quarter splits.
* **Multiple testing** is only partly corrected (p < 0.01, not a correction for the full grid size),
  so "WEAK" results are likely noise.
* **Fill models are approximations.** Maker fills are deliberately pessimistic (queue at back), so a KILL
  of a maker strategy (#29, #31, #32) is less certain than a KILL of a taker strategy.
* **Live forward tests were short** (≈4 h), so their $/day figures are orders of magnitude only.
* Net effect: KILL verdicts are reliable; PROMISING verdicts are hypotheses until they pass the holdout below.

**Rule from now on:** data after 2026-10-04 (live recordings, forward and paper trading) is the
**final holdout**. Choose strategies and parameters on history, confirm only on new data, and never tune
on that holdout. If a confirmation run fails, don't re-tune on the same data; collect fresh data.
