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
