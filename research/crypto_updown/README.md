# Crypto Up/Down markets: ideas #1, #19, #21, #31, #33, #34

Area: Polymarket's recurring crypto Up/Down windows (mostly the 5-minute ones; 15m/1h/4h for #19).
Every number here is net of **today's** crypto taker fee (`shares*0.07*p*(1-p)`), executed at a real ask or a real print, with no mid-price entries.
CIs are bootstrapped with clusters = window start time, because all coins in the same 5-minute window move together.
The split is chronological, 60% in-sample (IS) and 40% out-of-sample (OOS), unless stated otherwise.

## Verdicts

| # | Idea | Verdict | Key numbers (OOS unless noted) |
|---|---|---|---|
| 1 | Complement arb inside up/down markets | **KILL** (structural) | The Up and Down books are one mirrored book: `bu = 1-ad` and `au = 1-bd` in 99.95–99.996% of 26.9M ticks. "Crossings" show up in only 2–5 windows per coin in 56 days and almost never last 2 s or more. They are recorder glitches, not executable. |
| 19 | Gambler's fallacy / streak bias (5m) | **KILL** | The market's opening mid already moves against the streak (−0.41c per streak step, t≈−42). The realized up-rate moves the same way (IS −0.36c, t=−2.5; OOS −0.59c, t=−3.3). After 5 Ups: P(Up)=0.444 vs opening mid 0.470 (IS) and 0.451 vs 0.469 (OOS). The few-cent residual is smaller than half-spread + fee. Every fade/follow rule at the opening ask loses −8% to −16%. |
| 19b | Streaks on 15m / 1h / 4h | **WEAK** | Fading `|streak|≥4` on 15m returns IS +3.3% (p=0.11, n=1573) and OOS +8.3% (p=0.011, n=960). With a 1.5c half-spread: IS +1.5%, OOS +6.3% (p=0.04). 1h and 4h are not significant. Entry is the CLOB price-history price plus an assumed spread, not a recorded ask. |
| 21 | Fair value Φ(ln(S/K)/σ√τ) from Binance, taker | **KILL** | The model's log-loss is worse than the market mid in every time-left bucket. It adds only a little beyond the mid (logit coef 0.07–0.36). Best IS variant (margin 5c, τ 120–295 s): IS −1.0%, OOS −3.6% (n=15.5k). Every bucket and margin is negative OOS once the incident dates are excluded. |
| 21c | **Latency arb: Binance 1-s jump → take the stale Polymarket side (BTC 5m)** | **PROMISING-unconfirmed** (after the bias audit the history gives about +3–4% IS / +7% OOS; the 3.6 h forward test is +9% at ≥3 bp, p≈0.1; see the audit and forward sections) | Book fill at the first 1 Hz sample ≥ T+500 ms, threshold 5 bp: IS +6.8% (n=3041), OOS1 (Apr 12–26) +10.0% (n=1984), held-out OOS2 (Apr 27–May 18) +9.2% (n=880). Combined OOS +9.75%, CI [+7.3%, +12.4%]. All p<0.001. +1c slippage: 5.2% / 8.3% / 7.4%. With 2× latency (L=1000 ms, effective 1–2 s): IS +3.5%, OOS1 +8.5%. Print fills (first real print after T+500 ms): IS +10.6%, OOS +16.9%. Capacity is small: about $150–600/day at a ≤100-share cap. ETH: the edge is gone by 500 ms. |
| 31 | Maker-rebate harvesting near 50c | **KILL** | Quotes refreshed from a 1-s-old book: spread captured +0.55c per share, 5-s markout −2.3c per share (BTC), rebate +0.34c per share (that is 100% of the pro-rata pool share). Net about −2c per share. Even quoting from the same-second book still nets about −1c per share. Alts are worse (−3c to −6c). |
| 33 | End-of-window (final 2–60 s) taker/maker | **KILL** | Buying the favourite at the ask is −0.8% to −1.9% OOS (markets are calibrated, so the fee is the loss). The underdog is massively overpriced (ROI −43% to −99%), but the only way to sell it is to buy the favourite at the ask. A maker bid on the favourite: −4% to −7% OOS (adverse selection). The only "edges" were 1c lottery fills on 2026-04-29..05-04 recorder/oracle incident days. Those failed trade-print confirmation, so they are excluded. |
| 34 | Top-of-book imbalance alpha | **KILL** (as stated) | Imbalance coefficient ≈ 0.6–1.5c of mid move per unit imbalance. That is far below spread + fee (≥2.3c). The OOS R² of 1–17% comes almost entirely from the Binance lead-lag term, which is 21c. Combined taker (k=5, margin 2c): IS +2.0%, OOS +2.3% (p=0.046). At 2× latency it is −2.7%. |

## Data

* `kachoio/polymarket-5-minute-crypto-up-down-markets`: 89,233 five-minute windows, 7 coins, 1 Hz top of book (26.9M ticks).
  BTC runs 03-24→05-18; the other coins 04-05→05-18.
* Official outcomes: all 89,233 come from gamma-api `outcomePrices` (`fetch_gamma.py`). Agreement with other sources:
  kacho's final-tick outcome 99.86%, but it is null in 12.5% of windows and those nulls are biased toward close calls, so it must not be used alone.
  Chainlink-derived (aliplayer1 spot_prices, 03-30→04-26) 99.94%.
  Binance-derived (close ≥ open of the 1 s kline) only **96.5%**.
* Binance vs Chainlink basis: Binance BTCUSDT sits about −1 to −2 bp below Chainlink BTC/USD at window opens (sd 2–3 bp).
  The 5-minute move differs by sd 0.8–1.4 bp (move sd 10–16 bp). Binance therefore gives the wrong outcome sign in 3.5% of windows, nearly all of them close calls.
  A real bot should use Polymarket's RTDS Chainlink feed for the strike and late-window decisions.
* `aliplayer1/polymarket-crypto-updown`:
  * markets (to 04-20) and price histories (15m/1h/4h).
  * Websocket trade prints with ms server timestamps (BTC/ETH/SOL/XRP 5m, 03-14→04-26). Receive lag is 15 ms median, so the timestamps are server-side.
  * The orderbook BBO files were too large and HF rate-limited (429), so they were not used.
  * Ticks for markets after 04-20 were mapped to windows through gamma market ids (`fetch_gamma_ids.py`).
* Binance spot: 1 s klines (data.binance.vision, 6 coins, 03-23→05-19) and BTCUSDT aggTrades (ms; 03-24→05-18), ETHUSDT aggTrades (04-05→04-26).
  HYPE is not on Binance spot, so it has no spot-based tests.
* **Incident exclusion: 2026-04-29 → 05-04.** On these days the recorded books of ETH/SOL/XRP (less so the others) stopped converging to the official outcome.
  The final mid was on the wrong side in up to 30% of windows, against 1–2% normally.
  During those days "buy at 1c" trades looked like +100–400% ROI, but no trade prints exist to verify them and the matching prints in the verifiable period don't exist.
  The cause is a recorder or oracle incident, not a repeatable edge. All taker results above exclude these dates (see `summarize_all.py`).

## Execution model

* **Taker, 1 Hz books.** Decide on tick t using only information up to t.
  Binance input = the close of the 1 s kline that opened at t−1, i.e. the last trade before t.
  Execute on tick t+1 (stress: t+2) at that tick's ask if it is ≤ the ask seen at t (+tolerance), with size ≤ the displayed best size and ≤ $500.
* **Taker, sub-second (21c).** The event is a Binance aggTrade at time T whose 1 s return is ≥ thr bp, with a 5 s cooldown. Three fill models:
  * **book**: the recorded kacho ask at the first 1 Hz sample ≥ T+L, so the effective latency is L to L+1 s; size ≤ displayed size, ≤ 100 sh. Every event is filled, so there is no selection.
  * **first**: the first real taker print on that side with server timestamp ≥ T+L; size ≤ print size, ≤ 100 sh.
  * **worst**: the worst same-side print within 1 s after T+L, i.e. we sit behind faster bots.
  Each model is run with and without +1c. L = 250/500/1000/2000 ms, which covers the 150 ms speed bump plus feed, compute and network time.
* **Maker.** The quote is decided from the book at second s and is live during s+1. It is re-quoted every second, sized 50 sh per side, with inventory ≤ ±200 (or 1000) shares.
  It fills **only when a later taker print trades strictly through our price**: back of queue, filling ≤ 50% of the print.
  Optimistic variants are also run: "touch" fills, and quotes from the same-second book (`qlag0`).
  Held to resolution. Rebate = 20% × 0.07 × p(1−p) per filled share, which is our exact pro-rata share of the pool if every taker pays the fee. A 50% haircut variant is also reported.
* Positions are held to the official resolution. Quoted ROI = PnL / (cost incl. fees).

## #21c in detail (the one survivor)

BTC 5-minute windows. Each event is a ≥5 bp Binance move within 1 s; we buy the side the move favours.

| fill model | L | IS 03-24→04-12 | OOS1 04-12→04-26 | OOS2 held-out 04-27→05-18 |
|---|---|---|---|---|
| book ask (1 Hz, first sample ≥ T+L) | 250 ms | +8.4% (n=3049) | +12.4% (n=1992) | +11.0% (n=881) |
| book ask | 500 ms | +6.8% (3041) | +10.0% (1984) | +9.2% (880) |
| book ask + 1c | 500 ms | +5.2% | +8.3% | +7.4% |
| book ask | 1000 ms | +3.5% | +8.5% | +7.9% (876) |
| first print ≥ T+L | 500 ms | +10.6% (2186) | +16.9% (1795) | no prints after 04-26 |
| worst print in [T+L, T+L+1 s] | 500 ms | +1.5% (p≈0.2) | +6.9% (p=0.001) | – |
| worst print + 1c | 250 ms | +4.1% | +7.1% (p=0.004) | – |
| any fill model | 2000 ms | ≈0 to +4% | | |

How the edge behaves:
* The Polymarket price keeps catching up for about 2 s after the Binance move. Fill price minus the pre-event mid is +2.7c at 250 ms, +4.2c at 500 ms, +7.4c at 1 s and +10c at 2 s.
  The mid 10 s later is still above our fill price: +7 to +11c at 250–500 ms.
* The edge is spread over time-left buckets and is not concentrated in the last seconds, so Binance-vs-Chainlink noise does not drive it. It is positive on 29 of 33 days.
* At the 3 bp threshold it is smaller but still positive (book, L=500: IS +3.6%, OOS1 +3.8%, OOS2 +7.4%).
* At the 1 Hz level the same effect shows up in #34: the Binance return of the last second explains 15% of the next-second change in the Polymarket mid (BTC).
* **ETH reacts faster.** First-print fills at 250 ms: IS +6.1%, OOS +10.1%. At 500 ms ≈ 0, and book fills ≈ 0. Market makers there are quicker.

Caveats, and why it is "promising", not "proven":
1. Size. The median print is about 12 shares, the average book fill about 70 shares, and fills are capped at 100 shares. That is $150–600/day for BTC at this size.
   Ask-side depth beyond the best level was not recorded, so scaling is unknown.
2. Competition and regime. The data is Mar–May 2026. Fees, the taker delay (150 ms) and the resolution rule (60 s Chainlink TWAP since Aug 2026, single price before that) have changed since.
   TWAP settlement dampens late-window jumps but not mid-window ones.
3. The 1 Hz book fill could be optimistic if kacho's sampler lags the real book.
   On the other hand, it adds 0–1 s of extra latency, and the first-print fill (ms server timestamps) agrees.
4. **Next step:** a live recorder for BTC 5m/15m books (WebSocket, ms), Binance, and Polymarket RTDS Chainlink. Replay the same rule forward, then paper-trade it with real order round-trip timing.


## #21c bias audit (follow-up)

1. **Print timestamps.** The print-based variants use only `source='websocket'` ticks. Their `timestamp_ms` is the server time of the
   websocket trade message: local receive is 15 ms later (median, p99 120 ms). For the same trades, the on-chain (block) timestamps lag the
   websocket timestamp by **2.9 s** (median, IQR 2.1–3.6 s; 830k matched trades on 2026-03-20). On-chain timestamps were never used, so a
   print stamped after T+L was matched after T+L, give or take tens of ms. No settlement-lag bias.
2. **kacho 1 Hz book staleness** (`audit_kacho_lag.py`). For small prints the print price equals the displayed best quote:
   * 56–57% of the time at sample s or s+1;
   * 76% for prints in the first 250 ms of second s, falling to 41% for the last 250 ms;
   * the s+1 sample is the mirror image.
   So the sample labelled s reflects the book at about s+0.5 s. A book fill at the "first sample ≥ T+L" therefore runs at roughly
   L+1 s effective latency, which is conservative. Separately, displayed asks can be fake or stale. Two variants handle that:
   **print-confirmed** fills (a real same-side print at ≤ the displayed ask within [s+0.5 s, s+2 s]) and a **conservative price** of
   max(displayed ask, next real print). Results (`audit_21c.py`, BTC, 03-24..04-26, ≥5 bp):

| variant | L=500 IS | L=500 OOS | L=1000 IS | L=1000 OOS |
|---|---|---|---|---|
| book ask, all events | +6.1% (n=2315) | +9.5% (1917) | +3.0% | +8.1% |
| print-confirmed book fills only | +2.8% (p=0.06, n=1044) | +6.9% (p=0.002, 753) | −0.6% | +4.6% (p=0.01) |
| conservative price | +3.7% (p=0.003) | +7.1% (p<0.001) | +1.4% (p=0.17) | +6.8% (p<0.001) |

   Unconfirmed fills look better than confirmed ones, which means some displayed cheap asks were not really there. The honest
   historical edge is therefore about **+3–4% IS and +7% OOS at 500 ms**, and roughly 0–1% IS at 1 s.
3. **Taker delay.** The changelog says crypto taker delay was **250 ms until 2026-08-17** (then 50 ms; 150 ms since 2026-09-04).
   CLOB V2 went live 2026-04-28 with open orders wiped, which probably explains the 04-29..05-04 recorder incident. With a 250 ms delay,
   makers could cancel. Persistence of stale quotes (`audit_stale_curve.py`): the share of ≥5 bp events where a real same-side print
   still trades at ≤ the last pre-move price, within a 1 s window starting at T+X:

| T+X | share of events | mean shares |
|---|---|---|
| T+0 ms | 79% | 265 sh |
| T+300 ms | 60% | |
| T+550 ms (delay + 300) | **45%** | 162 sh |
| T+1 s | 29% | |
| T+2.5 s | 19% | (noise floor) |

   Stale quotes did survive past delay + 300 ms in about half of the events.

**Updated historical verdict:** WEAK-to-PROMISING. The edge is positive and significant OOS under every realistic fill rule, but small
in-sample under strict fills, and it decays to about zero at 1–2 s. The forward test below decides.


## #21c forward test in today's regime (2026-10-13 21:42 → 10-14 01:18 UTC, 3.6 h recorded, 111 resolved windows)

`live_fwd.py` recorded these streams, all with local receive ms:
* every Polymarket market-websocket message for the current and next BTC/ETH 5m and 15m windows (13.9M messages);
* Binance spot trades via data-stream.binance.vision (binance.com and binance.us are blocked here);
* Coinbase `matches`;
* Polymarket RTDS Chainlink prices.

`live_replay.py` rebuilds each Up book from `book` + `price_change`. The rebuilt best bid/ask disagrees with the server-reported
best_bid/best_ask on only 0.17% of 13.7M updates. Execution model:
* decision at our receive time of the spot trade;
* execution against the book at +150 ms delay + 100 ms RTT (measured one-way lag 12 ms; floored at 50 ms each way), plus variants with
  +300 / +500 ms;
* marketable limit at the decision ask + 2c, walking displayed depth, cap 100 sh, filling only levels that still exist;
* fee 0.07·p(1−p); settled on the official gamma outcome.

The lead-lag is still present today. After a ≥2 bp Binance move the Polymarket BTC mid moves +0.5c within 100 ms, +1.6c by 250 ms,
+4.1c by 500 ms and +5.3c by 1 s, so most of the repricing happens 250–1000 ms after the spot trade.

| signal | ≥thr | extra latency | trades/h | ROI | 95% CI | p | PnL (3.8 h) |
|---|---|---|---|---|---|---|---|
| Binance | 2 bp | 0 | 92 | +1.8% | [−4.4, +7.6] | 0.28 | +$286 |
| Binance | 3 bp | 0 | 29 | +9.3% | [−4.9, +25.7] | 0.10 | +$468 |
| Binance | 3 bp | +300 ms | 23 | +8.5% | [−3.5, +22.7] | 0.08 | +$408 |
| Binance | 3 bp | +500 ms | 23 | +10.1% | [+0.7, +22.6] | 0.017 | +$488 |
| Binance | 5 bp | 0 / +500 | 3 | +3.4% / +6.7% | | 0.18 / 0.03 | small |
| Coinbase | 2 bp | 0 | 171 | +1.0% | [−4.8, +7.1] | 0.38 | +$295 |
| Coinbase | 3 bp | 0 | 60 | +6.4% | [−1.9, +17.4] | 0.07 | +$750 |
| Coinbase | 3 bp | +300 / +500 ms | 46 | +2.1% / +2.3% | | 0.25 | |

Rows are pooled over BTC+ETH and 5m+15m. The average fill is 78 of the 100-share cap, and the average price is 0.62.
Trades with under 30 s left lost everything (n=14). Under 60 s TWAP settlement a late jump no longer decides the outcome, so a live rule
should require τ > 60 s.

**Forward verdict: INCONCLUSIVE, with the same sign as the history.** The ≥3 bp Binance signal earns +8–10% at every latency, but
3.6 h of quiet evening trading is too little data (p 0.02–0.10, with many variants tried). Taken at face value the PnL is about
$2.5–3k/day at a 100-share cap, but the CI includes 0. The next step is a multi-day recording, BTC/ETH 5m+15m only, at about 300 MB/h
raw. Compact the book deltas first, then re-run `live_replay.py` unchanged.

*2026-11-16:* `live_replay.py` now reads only the compact `pmc` stream and runs exactly the fixed test of the top-level
README (BTC 5m, Binance ≥ 3 bp, 250 ms, > 60 s left) plus its sensitivity rows. The raw-format version above is in git
history (commit 368053e and earlier). Results: the top-level README and `docs/LOG.md`.

## Other details

* **#19 (5m) table**, P(Up) and opening mid by previous streak. Streak = +k means k Ups in a row.

| streak | IS P(up) | IS mid0 | OOS P(up) | OOS mid0 |
|---|---|---|---|---|
| −5 or less | 0.534 | 0.534 | 0.533 | 0.531 |
| −3 | 0.536 | 0.515 | 0.515 | 0.515 |
| −1 | 0.507 | 0.496 | 0.498 | 0.498 |
| +1 | 0.508 | 0.503 | 0.495 | 0.503 |
| +3 | 0.496 | 0.487 | 0.492 | 0.484 |
| +5 or more | 0.444 | 0.470 | 0.451 | 0.469 |

  The market already prices short-horizon mean reversion. Opening asks are wide (alt spreads 3–9c at τ≈300 s), so taking at the open costs about 4c plus a 1.75c fee.
* **#21 Φ model**: per-coin parameters are in `out/idea21.json`. Fitted k≈0.85–1.1 (vol multiplier) and b≈0.8–3 bp (basis noise).
  The market mid beats the model's log-loss everywhere, most of all in the last 30 s, where the market sees Chainlink and we don't.
* **#31** per-share decomposition, OOS. Two-sided join-best quoting, band 0.35–0.65, stop at τ<60 s, 50-sh quotes, ±200 inventory.
  Trade prints run 03-24..04-26, split 60/40 by window.

| coin | quote from | spread captured | 5 s markout | P&L at resolution | rebate (100% pro-rata) | ROI on cost incl. rebate |
|---|---|---|---|---|---|---|
| BTC | 1-s-old book | +0.56c | −2.45c | −2.52c | +0.34c | −4.3% |
| BTC | same-second book (optimistic) | +0.57c | −1.26c | −1.31c | +0.34c | −2.0% |
| ETH | 1-s-old / same-second | +0.55c | −4.1c / −2.6c | −4.1c / −2.5c | +0.34c | −7.7% / −4.4% |
| SOL | 1-s-old / same-second | +0.62c | −4.9c / −3.2c | −5.1c / −3.5c | +0.34c | −9.8% / −6.6% |
| XRP | 1-s-old | +0.97c | −5.4c | −6.2c | +0.34c | −11.9% |

  Wider bands, touch fills, 1000-share inventory and stopping at τ<120 s all lose too (−1.5% to −13%).
  Fill rates are high only because stale quotes get picked off. That is the adverse selection.
  Fill rates are high only because stale 1 s quotes get picked off. That is the adverse selection.
* **#33**: verified with prints. In the period with prints, the fills that "won" in-sample lost 50% when a matching print existed (`verify_fills.py`).
* **#1**: a "sum of crossings if all captured" across all 7 coins is about $1.9k in 56 days. Those come from 2–5 glitch windows per coin with single-tick durations, which are not executable.

## Files

* Scripts:
  * `common.py` (loaders, taker simulator, incident flag)
  * `build_windows.py`, `build_panel.py`
  * `fetch_gamma.py`, `fetch_gamma_ali.py`, `fetch_gamma_ids.py`
  * `dl_binance.py`, `dl_ali_ticks.py`
  * `idea1_parity.py`, `idea19_streaks.py`, `idea19b_streaks_long.py`, `idea21_fairvalue.py`
  * `idea21c_subsecond.py` (print fills), `idea21c_bookfill.py` (book fills)
  * `idea31_maker.py`, `maker_sim.py` (numba fill engine), `idea33_endwindow.py`, `idea34_imbalance.py`, `verify_fills.py`
  * `summarize_all.py` → `result.json`
  * audit: `audit_kacho_lag.py`, `audit_21c.py`, `audit_stale_curve.py`
  * forward test: `live_fwd.py` (recorder), `live_replay.py` (replay)
* Outputs: small JSON/CSV results are in `out/`. Large intermediates (per-second panels, trade and fill parquet files) are in `data/ext/crypto/work/` (`common.OUT`). Logs are in `*.log`.
* Raw data: `data/ext/crypto/` (≈3.1 GB).
