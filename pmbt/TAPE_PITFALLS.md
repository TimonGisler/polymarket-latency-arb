# Pitfalls for tape-based tests (read before writing any tape backtest)

1. **Anchor on time known ex-ante.** "N hours before resolution" (using last_ts or resolution time) is
   LOOK-AHEAD: you don't know when a market will resolve; markets that resolve early (event happened)
   are systematically YES. Correct designs:
   (a) calendar-sampling: at decision times t (e.g. every day 12:00 UTC), consider all markets that are
       open at t (first_ts <= t, and still trading: there is a print after t is NOT knowable — use
       "had a trade in the previous 7 days and end_ts > t" or "created before t and not yet resolved at t"
       where resolution is approximated by last_ts > t; the residual bias of last_ts>t is small but
       state it), or
   (b) anchor on end_ts (scheduled end date, known ex-ante) — e.g. "T−24h before end_ts" — but then
       include markets that already stopped trading before T−24h as ALREADY RESOLVED (not tradable),
       i.e. only markets with a trade in the window before decision time qualify. Report how many
       markets resolve before end_ts by category.
2. **Executable prices only.** Entry = pmbt.tape.taker_entries (first same-side taker print after
   t+latency). Mid/last/VWAP are only for signals. Remember NO price = 1 − p.
3. **Clean outcomes only, decided before the test**: markets.resolved == True (yes_won in {0,1}).
   Report the share of excluded (unresolved/50-50) markets among those the strategy would have traded:
   a strategy can't avoid 50-50 resolutions in reality — treat 50-50 as payoff 0.5 if identifiable
   (outcome_prices ['0.5','0.5']) rather than dropping.
4. **Cluster by event_id.** Ladders/neg-risk legs are one bet.
5. **Huge recurring markets** (crypto up/down 5m/15m, `is_updown`) dominate trade counts since 2026 —
   analyze them separately from "normal" markets or exclude, otherwise they swamp the statistics.
6. **Category fees**: use pmbt.fees.taker_fee_per_share(p, category) on every taker fill.
7. **Capacity**: report $ actually fillable (avail_shares) and implied $/day; a 20% ROI on $50/day total is
   not a business.
8. **Data period**: tape ends 2026-10-04. OOS = entries on/after 2026-04-01.
9. Price units: p in [0,1]; tick sizes 0.01 (some 0.001). Prints at 0.999 / 0.001 exist.
10. Memory: never load the full tape into pandas. Push filters/aggregations into DuckDB SQL; read only
    months you need: read_parquet('data/derived/tape/month=2026-0*/*.parquet').
