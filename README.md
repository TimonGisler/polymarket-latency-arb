# polymarket-latency-arb

Research project for idea **#21c, the BTC 5-minute latency arb** on Polymarket. When BTC moves at least 3–5 bp within
one second on Binance, buy the side of Polymarket's 5-minute up/down market whose price hasn't caught up yet.

Split out of `polymarket-bot` (folder `parked/research/crypto_updown`, phase 1, done 2026-10-17) on 2026-11-15.
Nothing here depends on that repo.

## Where it stands
Updated 2026-11-22 (verdict). History: [docs/LOG.md](docs/LOG.md).

**VERDICT 2026-11-22: STOP.** The verdict rule says stop if real fills are clearly worse than the replay, and they are.
- **Replay, the fixed test, 7 days (11-15 18:22 → 11-21 end, 150 h): +3.0% ROI on cost, 95% CI [+1.4, +4.6]%,
  p < 0.001, 7,813 fills, 7 of 7 days positive.** That half passes. But it fell from +5–6% in the first days to
  +1.3–2.3% in the last three. And it depends on a 250 ms execution we don't get: at 500 ms it is +1.9% (p ≈ 0.01),
  and **at 1000 ms −0.3% (p ≈ 0.63)**, negative on each of the last 3 days (11-21 −2.5%).
- **Real orders (11-18 23:27 → 11-20 06:02, 890 orders, 5 shares): only 27% filled, against 81% on paper for the
  same signals.** Real result −$21.45 on 244 settled fills (ROI −2.3%, CI [−10.6, +4.5]%); about −$23.9 by wallet
  cash. Paper on the same signals made +5.2%, and all of it came from the orders that were killed in reality (+9.7%,
  p ≈ 0.001). On the signals where we really got filled, paper made −1.6%. So we only get filled when the price has
  not run away, which means on the trades with no edge (adverse selection).
- **Why it can't be fixed from our side:** Polymarket answers a taker order ~0.6–0.8 s after we send it (taker delay plus
  matching), and the book at that moment predicts our fill 190 times out of 192. A faster language or a closer server
  can't remove that delay, and at that delay the replay has no edge.
- Done 11-22: the trader is stopped and the compose file starts it in paper mode only (no `--live`). The recorder keeps
  running (cheap, ~0.25 GB/day) until the owner decides. **$6.08 is left on the test wallet**, and only the owner can move it.
- **Owner's options:** (1) **stop and archive** (recommended): stop the recorder and the nightly task, keep the
  repo; (2) the speed edge as a **maker** instead of taker: rest quotes and pull/reprice them on Binance moves.
  That is a different strategy and needs its own test, because maker cancels may face the same delay; (3) one more week
  of real orders: not useful, since 890 orders already settle the fill question.

Before the verdict (11-21): Replay over 6 days (126 h): +3.3%, p < 0.001, 6/6
days positive but falling (11-20 +1.3%), and only +0.6% (p ≈ 0.26) at the ~1 s our orders really take. Real money stopped at the $30 cap on 11-20 06:02: −$21.45 on
244 fills (loss ~$23.9 by wallet cash), only 27% of 889 orders filled (paper 81%), and the paper edge sits entirely in the
orders that were killed (+9.7%) while the filled ones made −1.6% ([LOG](docs/LOG.md#2026-11-20-nightly-session-2317-2350-utc)).
History after the bias audit: about
+3–4% per trade in-sample, +7% out-of-sample. A 3.6 h forward test on 2026-10-13: +9% at ≥ 3 bp, p ≈ 0.1 (not
significant). It's a speed race, and capacity is small: about $150–600/day at ≤ 100 shares. ETH has no edge left by
500 ms. All numbers and the audit: [research/crypto_updown/README.md](research/crypto_updown/README.md).

- Rules today are the ones the forward test ran under (150 ms taker delay, 0.07 fee, 60 s TWAP; checked 11-15).
- From this server Binance trades arrive ~135–144 ms late and a CLOB request takes ~53 ms round trip.
- **Replay so far (11-15 18:22 → 11-20 end, 126 h):** the fixed test **+3.3% ROI on cost, 95% CI [+1.6, +5.0]%,
  p < 0.001**, 5,517 fills, 6 of 6 days positive (11-19 +1.8%, 11-20 +1.3%). Slower execution (sensitivity rows):
  500 ms +2.1% (p ≈ 0.02), **1000 ms +0.6%, p ≈ 0.26** (11-19 and 11-20 −0.7% each): the edge fades at the delay
  our real orders actually have ([LOG](docs/LOG.md#2026-11-21-nightly-session-2317-2350-utc-prepares-the-verdict)).
- **Paper trader, first full day (11-17 23:24 → 11-18 23:17):** 680 settled paper fills, +4.8% ROI (100 sh), +4.7% at
  5 shares, win rate 57%: the same picture as the replay, live.
- **Real orders since 2026-11-18 23:27 UTC** (`trader.py --live`, 5 shares, FAK at ask + 2c, $30 loss cap in code).
  **First ~25 min: of 14 orders the paper (250 ms) would have filled 13, real ones filled 8**; the rest were killed
  (nothing left at the limit). Where both filled, the price was the same. Answer ~350–1400 ms after sending. Too few
  to judge yet, but this is the number the verdict hinges on. Polymarket redeems winners by itself; cash $19–29.
  **After ~8 h (11-19 07:13): real +$6.26 on 47 fills (+3.1%), but only 26% of 178 real orders filled vs 85% on
  paper for the same signals** (paper would have made +$46.76). Live chart on the dashboard.
  **Why:** Polymarket answers our orders only ~0.8 s (median) after we send them; the book at that moment predicts
  the real outcome for 190 of 192 orders (`fill_check.py`). The delay is on Polymarket's side (taker delay + matching), so
  neither Rust nor a closer server would fix it ([LOG](docs/LOG.md#2026-11-19-owner-session-0715-utc)).
  **After 24 h (11-19 23:14): real −$12.08 (cap use 12/30, cash $17.92), 208 of 717 real orders filled (29%; paper
  80%).** Paper ROI on the signals that really filled −0.8%, on the ones that were killed +8.1% (p ≈ 0.01): adverse
  selection. **Final (cap reached 11-20 06:02 UTC, real orders stopped, paper continues; `real_vs_paper.py`):** real
  −$21.45 on 244 settled fills (ROI −2.3%, CI [−10.6, +4.5]%), fill rate 27% vs paper 81% on 889 orders; paper on the
  same signals +5.2%, of it killed orders +9.7% (p ≈ 0.001), filled ones −1.6%. Wallet cash $6.08 stays there.
- The recorder runs since 2026-11-15 18:22 UTC. It leaks memory; since 11-17 it restarts itself cleanly
  above 200 MB, in the last minute of a window (~1 s gap; about every 8 h since 11-19).

## Plan
The question for 2026-11-22: **is this worth more of the owner's time?** One scheduled session a night does the next
open step ([docs/AUTOPILOT.md](docs/AUTOPILOT.md)). Update the Status column as you go.

| # | Step | Target | Status |
|---|---|---|---|
| 1 | Re-check rules, measure latency, start the recorder | 11-15 | **done** ([LOG](docs/LOG.md#2026-11-15)) |
| 2 | Make `live_replay.py` read the compact `pmc` stream (rebuild the Up book; Down = mirror). Find why 0.42% of rebuilt best prices disagree and count fills that touch a level of unknown size. Run [the test](#the-test-fixed-2026-11-15) on the first day as a dry run of the tooling, not as a result | night to 11-17 | **done 11-16** ([LOG](docs/LOG.md#2026-11-16)) |
| 3 | Build `trader.py`: the same rule in real time. Paper mode first (logs each decision, and the book when the order would have landed). The wallet is ready ([Needs the owner](#needs-the-owner)); work out how winning shares turn back into cash (redeem) so $30 keep trading | night to 11-18 | **done 11-17**: paper mode runs; redeem = `polymarket` SDK `redeem_positions`, gasless ([LOG](docs/LOG.md#2026-11-17-nightly-session-2317-2345-utc)) |
| 4 | Real orders at the minimum size (5 shares), $30 total loss cap in code, more than 60 s left in the window. Log for each order: sent, acknowledged, filled or not, fill price, and what the replay predicted for the same event. Needs the funded wallet | from 11-18 | **done 11-20 06:02** ($30 cap reached): real −$21.45 on 244 fills, fill rate 27% vs paper 81%; compare with `real_vs_paper.py` ([LOG](docs/LOG.md#2026-11-20-nightly-session-2317-2350-utc)) |
| 5 | Every night (after the verdict: health only, until the owner decides): health check; replay the finished days (`live_replay.py` with no arguments, ~10 min a day, in the `pmbot` image: command at the top of the script); one line in the LOG with the test so far, trades so far and disk free | nightly | health only since the verdict (11-26 23:17: all healthy; recorder running, trader stopped; waiting for the owner) |
| 6 | Verdict: [the test](#the-test-fixed-2026-11-15) on all recorded days, plus real fills against the replay's prediction. Write it at the top of this file and push it to the owner's phone. Done by the task "Latency-arb verdict" | **Sun 11-22 08:30 Zurich; on the phone by 12:00 at the latest** | **done 11-22: STOP** (replay +3.0%, p < 0.001, 7/7 days; at 1000 ms −0.3%; real fill rate 27% vs 81%, adverse selection) ([LOG](docs/LOG.md#2026-11-22-verdict-session-0730-utc)) |

**What the real orders are for.** $30 buys roughly 200–400 minimum-size trades (the fee alone is ~8c per trade). That
cannot prove profit. It answers what a replay can't: how often our order really fills at the price the book showed,
and how long an order really takes. The profit estimate comes from the replay, corrected by that fill rate.

**Verdict rule** (written before the data): continue if the fixed test is positive with p < 0.01 over at least 5 days
and positive on most days, **and** real orders fill at least about as often and as cheaply as the replay says. Stop
if the replay is not positive, or if real fills are clearly worse. Anything between: say so, and say what one more
week would settle.

## The test (fixed 2026-11-15)
Set before any new data was looked at. Never tune it on the recording; other settings may appear only as marked
extra rows.
- Market: BTC 5-minute up/down. Signal: Binance BTCUSDT moved ≥ **3 bp** within the last 1 s, seen at our receive
  time; buy the side the move favours; 5 s cooldown; only with **more than 60 s** left in the window.
- Execution: the order reaches the book **250 ms** after we received the Binance trade (150 ms taker delay + 100 ms
  for our round trip and compute; replace the 100 ms with the measured order round trip once step 4 has one).
  Marketable limit at the ask seen at decision + 2c, walking displayed depth, at most 100 shares, only levels that
  still exist then.
- Costs and outcome: fee `shares × 0.07 × p × (1−p)`, settled on the official gamma outcome.
- Statistics: ROI on cost including fees; bootstrap clustered by window; one-sided p; also per-day ROI.
- Sensitivity rows (not the verdict): execution at 200 / 350 ms (is a closer server worth it?), threshold 5 bp,
  Coinbase as the signal; from 2026-11-19 also 500 / 1000 ms (the measured real answer time).

## What runs
| What | Why | Check / stop |
|---|---|---|
| `latency-recorder` (container, [docker-compose.yml](docker-compose.yml)) | Records BTC 5m books and prints (compact `pmc`), Binance and Coinbase trades, Chainlink → `data/ext/crypto/live/`, ~0.25 GB/day in total; pauses under ~6.4 GB free disk (`df` Avail) | `docker logs --tail 3 latency-recorder`; `docker compose stop recorder` |
| `latency-dashboard` (container, [dashboard.py](dashboard.py)) | Read-only status page: is the recorder working, what it sees, plan, what the owner must do, orders (reads `data/status.json`, `data/trader/summary.json`, README, LOG) | **https://latency.77-42-11-137.sslip.io**, with the LP dashboard's login (`DASHBOARD_USER` / `DASHBOARD_PASSWORD` in `/root/polymarket-bot/.env`); on the server also `localhost:8081`. Served by the LP bot's caddy (last block of `/root/polymarket-bot/Caddyfile`) |
| `latency-trader` (container, [trader.py](trader.py)) | **Stopped 2026-11-22 (verdict); compose now starts it paper-only.** The fixed rule in real time: paper fills for every decision, and **real 5-share orders** (`--live`, key from `.env.wallet`, $30 loss cap counted from the log, winners redeemed every 5 min). Writes `data/trader/decisions.jsonl` (decisions, paper execs, real orders, settlements; state is rebuilt from it on restart) and `summary.json` (dashboard). Leaks memory like the recorder: exits cleanly above 100 MB in the last minute of a window, docker restarts it | `docker logs --tail 3 latency-trader`; `docker compose stop trader` (stops real orders); paper only: drop `--live` in the compose file |
| Scheduled tasks "Latency-arb nightly" (00:17 Zurich) and "Latency-arb verdict" (Sun 11-22 08:30 Zurich), both Opus | Run the plan | [docs/AUTOPILOT.md](docs/AUTOPILOT.md) |

## Needs the owner
- **The verdict (2026-11-22): choose an option at the top of "Where it stands"** (recommended: stop the recorder and the
  nightly task). $6.08 stays on the test wallet until you move it.
- The wallet (2026-11-15): key in `/root/polymarket-latency-arb/.env.wallet` (`PK=...`,
  root-only, gitignored), $30 put into its Polymarket proxy `0xF82E76a7fDa4Df8ED7D88545B3180B7C20FE45C0`
  (`signature_type=1`); the trader spends it since 2026-11-18 (cash and loss on the dashboard). The redeem key it
  creates is in `.env.builder` (root-only, gitignored). Check it any time, read-only: see the top of [wallet_check.py](wallet_check.py).
- Later, not urgent: the disk (19.9 GB free on 2026-11-17, up from 8.5 GB; this recorder uses ~0.35 GB/day).

## Layout
- `research/crypto_updown/`: the study (scripts, `out/` small results, `result.json`). It also holds the other
  crypto up/down ideas from phase 1 (#1, #19, #21, #31, #33, #34), all rejected.
- `pmbt/`: tape backtest library and **the testing rules for taker strategies** ([pmbt/README.md](pmbt/README.md),
  [pmbt/TAPE_PITFALLS.md](pmbt/TAPE_PITFALLS.md)): executable prices only, today's fees, no look-ahead, clustered
  bootstrap CIs, p < 0.01, sized results; data after 2026-10-04 only for confirmation. Copied from
  `polymarket-bot/parked/pmbt` (the UMA study there still uses its own copy).
- [CLAUDE.md](CLAUDE.md): rules and background for every session. [docs/LOG.md](docs/LOG.md): history.
  [docs/AUTOPILOT.md](docs/AUTOPILOT.md): how it runs unattended, and the limits. `scripts/`: phone push, end of session.
- [POLYMARKET_DATA.md](POLYMARKET_DATA.md): gotchas of Polymarket's historical data.
- `requirements.txt`: Python packages (copy of the main repo's at the time of parking).
- `data/` (gitignored): the live recording since 2026-11-15 (`data/ext/crypto/live/`). The historical data was never on the server and the old forward recordings are lost; re-download history with the
  `dl_*.py` / `fetch_gamma*.py` scripts. Scripts find `data/` relative to the project root.

## Sessions
Remote Control serves this folder as `polymarket-latency-arb` (systemd `claude-rc-latency.service`, loop script
`/usr/local/bin/claude-rc-latency-loop.sh`). Console: `tmux -L claude-latency attach` (detach: Ctrl-b d).
