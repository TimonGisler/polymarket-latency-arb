# Log
Add-only, newest at the bottom. Dated UTC. Findings, decisions and rejected options, with numbers. Correct an old
entry with a new one. Current state and the plan: [README](../README.md).

## 2026-11-15
Owner: wants to know within a week (by 2026-11-22) whether this is worth more time; wants to do nothing himself;
offers $20–30 for an early real-order test; would buy a closer server if it clearly helps. Plan: [README](../README.md#plan).

**Rules re-checked** (docs.polymarket.com/changelog.md, read today): nothing changed for this idea since the forward
test of 10-13. Crypto taker delay 150 ms (since 09-04), 5m markets settle on a 60 s Chainlink TWAP, crypto taker fee
rate 0.07 with 20% maker rebate (the market's own `feeSchedule` from gamma says the same). RTDS (our Chainlink feed)
is called legacy but still delivers.

**Latency from this server** (Hetzner Helsinki), measured once, ~18:15 UTC:
- Polymarket CLOB `GET /time` on an open connection: median 53 ms round trip (48–99; through Cloudflare's Helsinki edge).
- Binance trades (`data-stream.binance.vision`): received a median **144 ms** after the trade's own timestamp (p10 139,
  p90 265; n=1612; server clock NTP-synced). `api.binance.com/time` takes ~260 ms round trip, so Binance's matching
  engine is far away (Asia). The 10-13 forward test ran in a cloud container that saw Binance only ~12 ms late, so
  **we see the signal ~130 ms later than that test did**; its "+300 ms" row (+8.5%, p=0.08) is the closest to our position.
- Polymarket's own feeds: `crypto_prices` (Binance) arrives ~300 ms, Chainlink ~1.3 s after its timestamp.
- Geoblock: `blocked:false, FI`.

**Server move: not now.** Total delay is about 144 ms (Binance → us) + ~25–50 ms (us → CLOB) + 150 ms taker delay.
The signal has to travel from Binance (Asia) to Polymarket (reportedly London; not verified) on any server; the detour
through Helsinki costs perhaps 30–40 ms of ~350. The replay reports the result at −50 / +0 / +100 ms as a sensitivity
check; only if those differ clearly is a server worth it. The UK is on Polymarket's restricted list, so "next to the
CLOB" is not simply London.

**Recorder started 18:22 UTC** (`docker compose up -d recorder`, container `latency-recorder`, 300 MB limit, 27 MB used).
- Raw recording is too big for this disk: BTC 5m alone is ~4 GB/day raw-gzipped (540 level changes/s), and the disk has
  8.5 GB free, which the LP bot's recorder also needs (it stops itself at 5 GB free, about 11-28).
- So `live_fwd.py` now writes a compact stream `pmc` by default: Up token only (Down is the mirror), only levels within
  15c of the best bid/ask. Measured ~160–190 MB/day, plus ~50 MB/day for Coinbase trades: ~1.6 GB for the week. It pauses writing under ~6.4 GB free (`df` Avail).
  `--raw` keeps the old format. Also: `--coins`, `--tfs`; gamma lookup uses urllib (the `pmbot` image has no curl).
- Check on the first 40 s: books rebuilt from `pmc` disagree with the server's best bid/ask on 0.42% of 13.7k changes
  (raw format on 10-13: 0.17%). Cause not looked at yet (the 15c band, or the first changes before a snapshot).
- Risk of the band: after a jump of more than 15c with no snapshot in between, a level's size may be unknown. Snapshots
  come ~5–10 per second, so this should be rare; the replay must count how often it fills against such a level.
- `live_replay.py` still reads only the raw format. Adapting it is the next step.

**Test settings, fixed today before any new data was looked at** ([README](../README.md#the-test-fixed-2026-11-15)).

**Real-money test:** owner's offer recorded as a go-ahead for at most $30 total loss, on a balance separate from the LP
pilot. Which wallet is open: [README](../README.md#needs-the-owner).

**This repo has no git remote.** It exists only on this server. Not fixed today (needs the owner to create a GitHub repo).

**Status page built** (`dashboard.py`, container `latency-dashboard`, 15 MB): recorder state from `data/status.json`
(the recorder now writes it every 10 s), current book and Binance price, Binance lag, disk, hours recorded, then the
README's "Needs the owner", "Where it stands", "Plan", orders (`data/trader/summary.json`, a flat `{label: value}`
object the trader should write) and the newest LOG entry. It uses the LP dashboard's login. Works on
`localhost:8081`; **not public**: that would go through the LP bot's caddy, which this session was not allowed to
change; it waits for the owner ([README](../README.md#needs-the-owner)).
The recorder was restarted three times today for these changes (18:25, 18:33, 18:34 UTC; a few seconds missing each).

**Status page public, ~18:37 UTC:** the owner said yes, so the LP bot's Caddyfile got one more site
(`latency.77-42-11-137.sslip.io` → `latency-dashboard:8080`; appended with `cat >>` because the file is bind-mounted
and a replaced file would not be seen), validated and reloaded, not restarted. Checked: new page 200 with the login and
401 without, LP dashboard still 200, caddy "Up 7 days". Committed in polymarket-bot. This was a one-off approval;
other changes to the LP bot still need the owner.

**Wallet received and checked, ~18:45 UTC** (`wallet_check.py`, read-only, no orders). The owner gave a key for a
separate Polymarket account; it is in `.env.wallet` (root-only, gitignored). API access works. Signer
`0x372baC7ad43643A69Ea33Fe6Dc22Ad8A4a700607`; cash **$30.00 in the proxy** `0xF82E76a7fDa4Df8ED7D88545B3180B7C20FE45C0`
(`signature_type=1`, trading allowance set), $0 in the safe and the EOA, 0 open orders. It is an older account, not a
fresh one: ~100 past trades (2025), a redeem on 2026-10-18, and two resolved losing positions worth $0 that still show
as "redeemable". So the trader must count only its own trades, not the account's history. The key was pasted in the
chat, so treat it as a $30 test wallet only; a new key before any larger amount.

**Owner, ~19:30 UTC:** (1) verdict on his phone by Sunday 2026-11-22 ~12:00 Zurich at the latest: one-off task
"Latency-arb verdict" set for 08:30 Zurich that day. (2) Scheduled sessions must run at least Opus: both tasks set to
`claude-opus-5-5` (the nightly one had the default model before). (3) Remote: `origin` =
`git@github.com:TimonGisler/polymarket-latency-arb.git` (the owner created the empty repo). The LP bot's key can't push
here: GitHub deploy keys work for one repository only. A new key `/root/.ssh/github_deploy_latency` was made and this
repo uses it (`core.sshCommand`, so `~/.ssh/config` is unchanged); the owner has to add its public part as a deploy key
with write access. Until then pushes fail and the work stays in the local commits.

**Deploy key added by the owner; first push to GitHub done (~19:40 UTC).** Sessions now commit and push.

**Chainlink stream had stopped; recorder fixed; restart damage in the files found and repaired** (owner's request,
done from the server session `bot-server-home`, ~21:45–22:05 UTC).
- **Chainlink (`cl`) gaps:** no prices from about 20:15 to 20:32 and from 20:55 to 21:46 UTC. The RTDS socket stays
  open and answers, but the feed goes silent; the recorder only reconnected when the server closed the socket
  (20:32, "Going away"). A fresh connection gets prices at once (16 in 8 s). Fix: `RTDS_STALE_S` in `live_fwd.py`,
  30 s without a price = reconnect. The other streams had no gap. The health check in AUTOPILOT did not look at `cl`.
- **Restarts made hour files unreadable.** A killed recorder leaves a gzip member without its end, the next start
  appends to the same hour file, and `gzip`/`zcat` stop at the junction. Hour 18 had 4 such parts (the starts of
  18:22–18:33): a normal reader saw 37,122 of 560,636 `pmc` lines. Nothing was lost on disk except up to 10 s before
  each kill. `scripts/fix_gz.py` rewrites such files as clean gzip (originals in `data/ext/crypto/live_damaged/`,
  6.5 MB, delete when the replay has read the repaired files). Hour 18 repaired: `bn` 49,714, `cb` 109,065, `cl` 4,369,
  `pmc` 560,636 lines.
- **Clean shutdown:** `live_fwd.py` now closes its files on SIGTERM (`docker stop`, `restart`). Tested in a throwaway
  copy: 30 s of recording, `docker stop`, all five files pass `gzip -t`. An OOM kill or crash still needs `fix_gz.py`.
- Recorder restarted 21:46 and 21:49 UTC for these two changes: two gaps of about 15 s in all streams, and hour 21
  got two more junctions (the 21:46 one was a kill); repaired with `fix_gz.py` after 22:00.

## 2026-11-16
**Check 08:00 UTC (server session `bot-server-home`): recorder healthy; the nightly session did not run.**
- Hour 21 of 11-15 repaired at 22:01 (`pmc` 891,059, `bn` 128,694, `cb` 175,102, `cl` 1,609 lines); all 75 finished
  files pass `gzip -t`. 182 MB recorded so far.
- Since the fix (11-15 22:00 → 11-16 08:00): no gap over 30 s in `pmc` and `bn`; `cl` two gaps of 33 s (02:05, 05:16),
  both the new watchdog reconnecting after the feed went silent. It works.
- **The nightly task of 23:17 UTC failed within a second: "You've hit your session limit · resets 12:30am (UTC)"**
  (the owner's shared Claude limit). No plan step was done that night. The LP bot's operator tick at 22:07 failed the
  same way. Both left their Claude process behind (~190 MB each).

## 2026-11-16 (nightly session, ~23:17–23:55 UTC)
**Plan step 2 done: `live_replay.py` reads `pmc` and runs exactly the fixed test. Dry run on the first 30 h
(11-15 18:22 → 11-16 ~23:40), not a result:** TEST +4.9% ROI on cost, 95% CI [+1.0, +9.0]%, one-sided p = 0.004,
964 fills in 254 windows, avg 86 shares at 0.55, PnL +$2,284 on $47k cost (≈ $1.8k/day at a 100-share cap, before any
real-world fill shortfall). Per day: 11-15 evening +12.4% (112 fills), 11-16 +3.6% (852 fills; p = 0.05 alone).

| row (sensitivity rows are not the verdict) | fills | ROI | p |
|---|---|---|---|
| TEST: Binance ≥ 3 bp, 250 ms | 964 | +4.9% | 0.004 |
| exec 200 ms | 1023 | +5.1% | 0.007 |
| exec 350 ms | 867 | +5.8% | 0.004 |
| ≥ 5 bp | 229 | +3.6% | 0.13 |
| Coinbase ≥ 3 bp | 1182 | +5.9% | 0.002 |

- Of 1,170 decisions, 206 found nothing at or below the limit (no fill); fills averaged 0.75c above the decision ask.
  1,026 signals came with ≤ 60 s left, 329 with no ask on the side.
- **Worth flagging:** 350 ms is no worse than 200 ms (the 10-13 test showed the same: +500 ms as good as 0). If that holds
  over the week, the edge is more short-term momentum than a race, and a closer server would not help. It also means the
  real-order step can still work with our ~144 ms Binance lag.
- **Book rebuild from `pmc`:** the 0.42% of 11-15 was a per-row count while a message is half applied. Compared after
  each whole message, the rebuilt best bid/ask disagrees with the server's on 0.066% of 30.5M live-window messages
  (11-16); 97% of those are "phantom" levels (we still hold a level the server's best says is gone), only 2% fall outside
  the known 15c band, and the next snapshot (~6/s, one after every trade) clears them: snapshots disagree with the
  rebuilt best 131 times in 450k. **Fills touching a level of unknown size: 0 of 964. Fills taken while the rebuilt
  best disagreed: 1.** The band is not a problem.
- Replay is per UTC day (`data/replay/<day>.parquet`, ~9.5 min and < 1 GB per full day in the `pmbot` image); with no
  arguments it does every finished day not yet replayed whole, then the report. AUTOPILOT now has the nightly replay as
  its step 2, so Sunday's verdict only needs the last day plus the report. 11-16 was replayed before it ended and will
  be redone by the next night automatically.
- Health 23:17 UTC: recorder up 25 h, every counter rising (pmc 44.3M, bn 4.64M, cb 2.14M, cl 181k); the Chainlink
  watchdog reconnected once at ~23:03. Disk 20.5 GB free (was 8.5 GB on 11-15; freed outside this project), recording
  441 MB so far. No restart, nothing to repair. Trades: none (no real orders yet).
- The nightly run of 11-15 failed on the Claude usage limit (entry above); this run did the step it missed.

## 2026-11-17 (nightly session, ~23:17–23:45 UTC)
**Plan step 3 done (paper part): `trader.py` runs the fixed rule in real time, paper mode, as container
`latency-trader` since 23:24 UTC. Replay with 11-16 now complete: TEST +4.7% ROI, p = 0.012, 970 fills, both days
positive; p is no longer below 0.01 (the partial 11-16 had given 0.004). Recorder had a memory leak; fixed with a clean
self-restart.**

| row (30 h, 11-15 18:22 → 11-16 24:00; sensitivity rows are not the verdict) | fills | ROI | p |
|---|---|---|---|
| TEST: Binance ≥ 3 bp, 250 ms | 970 | +4.7% [+0.6, +9.0] | 0.012 |
| exec 200 ms | 1033 | +5.0% | 0.005 |
| exec 350 ms | 872 | +5.7% | 0.004 |
| ≥ 5 bp | 230 | +2.9% | 0.20 |
| Coinbase ≥ 3 bp | 1190 | +5.7% | 0.000 |

- Per day (TEST): 11-15 evening +12.4% (112 fills), 11-16 +3.5% (858). PnL +$2,230 on $47.3k cost at ≤ 100 shares.
  Still 350 ms ≥ 200 ms. 11-17 gets replayed by the next night (only finished UTC days).
- **`trader.py` (paper):** own Binance and Polymarket websockets, the same rule as `live_replay.py` (1 s lookback in
  exchange time, 3 bp, 5 s cooldown, > 60 s left, ask + 2c, Down = 1 − Up bids). Logs each decision with the top 5 levels,
  and 250 ms later the book again with the paper fill at ≤ 100 shares and at the 5-share size step 4 will send;
  settles on gamma. Output `data/trader/decisions.jsonl`, `data/trader/summary.json` (on the dashboard). Executions land
  0–3 ms after the 250 ms mark; Binance lag 135 ms median; 30 MB memory. Checked against the recorder: the first signal's
  Binance trade is in the recording too (trader received it 12 ms before the recorder). Its counters and unsettled paper
  fills start fresh on restart (paper only; step 4's loss cap must persist).
  Seen at once: the book often moves in those 250 ms (one fill: ask 0.89 → 0.91, 4.4 of 100 shares).
- **Redeem (for step 4):** as the LP bot's merger does (`/root/polymarket-bot/bot/positions.py`, read only): the
  `polymarket` SDK in the `pmbot` image, `SecureClient.create(private_key=PK, wallet=<proxy>)`, once
  `create_builder_api_key()` (store in this repo's `.env.builder`, gitignored), then
  `redeem_positions(condition_id=...).wait()`: gasless via the relayer, works for a proxy wallet (`signature_type=1`),
  redeems tested for real by the LP bot on 11-04. Trader: redeem each won window a few minutes after it resolves.
  To check in step 4: a 5-share buy below 0.20 is under $1; whether the CLOB has a $1 minimum for marketable orders.
- **Recorder memory leak:** 295 MB resident + 133 MB in swap after 49 h (started at ~28 MB, ≈ 9 MB/h), pinned at its
  300 MB cap and swapping (cgroup `max` events 1.86M, no OOM kill yet). Swapping can delay our receive timestamps and
  eats the server's shared swap. Leak not found. Fix: `live_fwd.py` exits cleanly (files closed) when resident + swap
  > 200 MB, only in the last 60 s of a 5m window (no decisions then); docker restarts it in ~1 s. Expect a restart
  about every 20 h. Restarted once by hand at 23:29:05 (second 245 of the window): ~1 s gap, all streams back.
- Health 23:18 UTC: recorder up 2 days, every counter rising (pmc 80.3M, bn 9.24M, cb 3.88M, cl 351k), 19.9 GB free.
  Trades: none (paper only).

## 2026-11-18 (nightly session, 23:17–23:50 UTC)
**Plan step 4 started: real 5-share orders run since 23:27 UTC (`trader.py --live`, $30 loss cap). Replay over 3 days
(54 h): TEST +5.4% ROI on cost, 95% CI [+2.5, +8.3]%, p < 0.001, 1,895 fills, all 3 days positive. Paper trader's first
full day: +4.8% on 680 fills. Not a verdict yet (needs ≥ 5 days and the real fills).**

| row (54 h, 11-15 18:22 → 11-17 24:00; sensitivity rows are not the verdict) | fills | ROI | p |
|---|---|---|---|
| TEST: Binance ≥ 3 bp, 250 ms | 1895 | +5.4% [+2.5, +8.3] | < 0.001 |
| exec 200 ms | 1994 | +5.7% | < 0.001 |
| exec 350 ms | 1681 | +5.6% | < 0.001 |
| ≥ 5 bp | 494 | +6.8% | 0.001 |
| Coinbase ≥ 3 bp | 2318 | +4.1% | 0.003 |

- Per day (TEST): 11-15 evening +12.4% (112 fills), 11-16 +3.5% (858), 11-17 +6.1% (925). PnL +$4.7k on $88k cost at
  ≤ 100 shares (≈ $2.1k/day before any real-world fill shortfall). 350 ms still as good as 200 ms.
- **Paper trader (11-17 23:24 → 11-18 23:17):** 832 decisions, 680 paper fills, 151 nothing at the limit; settled
  +$1,479 on $30.8k (+4.8%) at ≤ 100 shares, +4.7% at 5 shares; win rate 56.8%; Binance lag 145 ms median.
- **Trader memory leak:** at 128 MB cap + 65 MB swap after 24 h (cgroup `max` events 144k), and 22 Polymarket
  disconnects "1013 slow consumer: send buffer full" (it was too slow to read the socket). Same leak as the recorder
  (both use per-window `websockets` connections; not found). Fix as in the recorder: clean exit above 100 MB in the
  last minute of a window; the trader now rebuilds its counters, unsettled fills and the real-money ledger from
  `decisions.jsonl` on start (checked: the rebuilt totals equal the running ones to the cent).
- **Real orders (step 4), what was built:** on each decision, a FAK buy of 5 shares at ask + 2c (the paper limit) is
  signed and posted at decision time in a worker thread; the answer is logged as `ev: "order"` next to the paper
  `exec` of the same id (the replay's prediction for that event). Loss cap: $ paid (incl. fee) for all real fills minus
  $ won on settled ones; open positions count as lost; no order once that plus the next order would pass $30. Winners
  are redeemed every 5 min (data-api `redeemable` → `polymarket` SDK `redeem_positions`, as the LP bot does; key in
  `.env.builder`). Wallet cash is read every minute (dashboard).
- **What the first orders showed:** one manual test order at 23:25 (5 Up @ 0.46 filled, $2.30 + fee $0.08694 =
  5 × 0.07 × 0.46 × 0.54: **the fee is charged in cash on top, exactly the test's formula**; gamma's `feeSchedule` still
  says rate 0.07, exponent 1, taker only). Then in the first minutes: 4 filled (Down at limits 0.94–0.99; fill prices
  equal to the paper's 250 ms fill), 2 killed "no orders found to match" (nothing left at the limit; the paper had
  filled one of them at 0.59), 1 rejected: **the CLOB refuses marketable buys under $1**, so 5 shares need a limit
  ≥ 0.20 (now skipped and counted). Exchange answer 350–530 ms after sending; signing took 15 ms warm, 36–50 ms at the
  container's 0.5 CPU, so the trader now has 1 CPU. FAK fills can be a bit over 5 shares (5.05).
- **First comparison, 23:27–23:47 (14 orders with a limit ≥ 0.20): paper 5-share fill at 250 ms 13 of 14, real fill
  8 of 14; where both filled, the same price.** If real orders keep missing that often, our orders land later than the
  test's 250 ms (answers came 350–1400 ms after sending; the CLOB's match time has only 1 s resolution) and the
  replay's profit has to be cut by the real fill rate. Too few orders yet; the verdict will have a few hundred.
- Settlement: **Polymarket redeemed the resolved winners itself** within minutes (positions gone, cash back: 7 fills,
  2 lost, cash $29.03 at 23:40). The trader's own redeem (fallback) had read data-api v1 keys, which v2 doesn't send;
  fixed, and found nothing to redeem. Ledger at 23:48: $36.1 paid, $25.3 won, settled PnL −$0.97, cap use $10.75/30.
- Still seen after the restart: Polymarket "slow consumer" disconnects (1 in 20 min) with low memory, so not only
  swapping: probably `get_json` (gamma, blocking, up to 20 s) inside the event loop in discovery/settle. Not fixed
  tonight; a candidate for the next session (move those calls to a thread).
- Health 23:17 UTC: recorder up 8 h (its memory self-restart at 15:14 worked, ~1 s gap; nothing to repair:
  `fix_gz.py` found no damaged file), every counter rising; Chainlink watchdog reconnects now and then as before.
  Disk 18 GB free. Trader up, summary current.

