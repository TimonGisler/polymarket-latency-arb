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
