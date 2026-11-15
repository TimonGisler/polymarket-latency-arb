# polymarket-latency-arb

Research project for idea **#21c, the BTC 5-minute latency arb** on Polymarket. When BTC moves at least 3–5 bp within
one second on Binance, buy the side of Polymarket's 5-minute up/down market whose price hasn't caught up yet.

Split out of `polymarket-bot` (folder `parked/research/crypto_updown`, phase 1, done 2026-10-17) on 2026-11-15.
Nothing here depends on that repo.

## Where it stands
**PROMISING, unconfirmed.** History after the bias audit: about +3–4% per trade in-sample, +7% out-of-sample.
A 3.6 h forward test on live data: +9% at ≥ 3 bp, p ≈ 0.1 (not significant). It's a speed race, and capacity is
small: about $150–600/day at ≤ 100 shares. ETH has no edge left by 500 ms. All numbers and the audit:
[research/crypto_updown/README.md](research/crypto_updown/README.md). No real orders have ever been placed.

## Next steps (no money until step 3 is clearly positive)
1. **Measure latency from the server** (Helsinki) to `clob.polymarket.com` and to the Binance stream. The edge exists
   only at sub-second latency, so it may not exist from this server.
2. **Record 1–2 weeks** with `python3 research/crypto_updown/live_fwd.py --hours <h>` (writes `data/ext/crypto/live/`).
3. **Replay** with `python3 research/crypto_updown/live_replay.py` at the measured latency. The key question is
   whether orders would actually fill at the stale price, not only whether the signal predicts the move.
4. Only if significant over several days: paper-trade in real time, then tiny size. Require > 60 s left in the
   window (settlement uses a TWAP).

## Layout
- `research/crypto_updown/`: the study (scripts, `out/` small results, `result.json`). It also holds the other
  crypto up/down ideas from phase 1 (#1, #19, #21, #31, #33, #34), all rejected.
- `pmbt/`: tape backtest library and **the testing rules for taker strategies** ([pmbt/README.md](pmbt/README.md),
  [pmbt/TAPE_PITFALLS.md](pmbt/TAPE_PITFALLS.md)): executable prices only, today's fees, no look-ahead, clustered
  bootstrap CIs, p < 0.01, sized results; data after 2026-10-04 only for confirmation. Copied from
  `polymarket-bot/parked/pmbt` (the UMA study there still uses its own copy).
- [CLAUDE.md](CLAUDE.md): rules and background for every session.
- [POLYMARKET_DATA.md](POLYMARKET_DATA.md): gotchas of Polymarket's historical data.
- `requirements.txt`: Python packages (copy of the main repo's at the time of parking).
- `data/` (gitignored): **empty.** The historical data was never on the server and the old forward recordings are lost; re-download history with the
  `dl_*.py` / `fetch_gamma*.py` scripts. Scripts find `data/` relative to the project root.

## Sessions
Remote Control serves this folder as `polymarket-latency-arb` (systemd `claude-rc-latency.service`, loop script
`/usr/local/bin/claude-rc-latency-loop.sh`). Console: `tmux -L claude-latency attach` (detach: Ctrl-b d).
