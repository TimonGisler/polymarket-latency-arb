# polymarket-latency-arb

Goal: find out whether idea **#21c, the BTC 5-minute latency arb**, makes real money from our server, and if
so build it. Current state, numbers and next steps: [README.md](README.md). Full study:
[research/crypto_updown/README.md](research/crypto_updown/README.md).

## Memory
- The repo is the only memory. The owner switches sessions often; assume the next one knows nothing.
  Write findings and decisions into the repo (README "Where it stands", plus a dated `docs/LOG.md` entry
  once there is one), then commit.
- All times UTC, dates absolute (YYYY-MM-DD). Report results honestly, including negative ones: result first.

## Background worth knowing (from phase 1, polymarket-bot `parked/research/03_results.md`)
- Of 40 ideas tested, only two taker edges survived: this one and #6b UMA-proposal sniping (decaying,
  stays in polymarket-bot `parked/`). Wallet analysis of top earners: the money is in providing liquidity
  and in **speed**, not in predicting outcomes, which supports this idea.
- Regime the forward test ran in: 150 ms taker delay, 60 s TWAP settlement, 7% crypto taker fee
  (`fee = shares × 0.07 × p × (1−p)`, in `research/crypto_updown/common.py`). Polymarket's mid lagged
  Binance by ~0.5–1 s. Fees and these rules changed during 2026; re-check them before trusting old numbers.
- **No data is on the server.** The historical crypto data was never copied here, and the 3.6 h forward
  recording plus a 12 h extension lived in a phase-1 container that is gone. Only the small results in
  `research/crypto_updown/out/` survive. Start by recording fresh.

## Rules
- **Testing rules for taker strategies:** [pmbt/README.md](pmbt/README.md),
  [pmbt/TAPE_PITFALLS.md](pmbt/TAPE_PITFALLS.md). Executable prices only, today's fees, no look-ahead,
  p < 0.01, fix settings before a forward run and never tune on it.
- **No real money without the owner's explicit go-ahead.** No session moves money off a wallet. The wallet
  (`.env.wallet` in `/root/polymarket-bot`) belongs to the LP bot's live pilot; trading here needs the
  owner to decide which wallet and how much.
- **Shared server:** this runs on the same server (Helsinki, 4 GB RAM) as polymarket-bot's live LP bot and
  recorder, which are running. Don't stop or restart their containers, and keep memory and disk use
  small (the LP recorder needs the disk; check `df -h` before recording for long).
- Keep it simple. Never write down secrets, only where they live.
