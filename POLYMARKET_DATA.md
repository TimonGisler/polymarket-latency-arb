# Historical data gotchas (taker research)
Moved from the main repo's `docs/POLYMARKET.md` on 2026-10-25. Paths are relative to `parked/`.

- **Historical trades:** HF `SII-WANGZJ/Polymarket_data` `trades.parquet` (1.27B fills through
  2026-10-04).
  - Each row is one maker fill at the maker's price.
  - YES-normalize: if `nonusdc_side == 'token2'`, YES price = 1 − price, and taker-bought-YES =
    `(taker_direction == 'BUY') XOR (side == 'token2')`.
  - Build the compact local tape with `python research/data_build/build_tape.py [SINCE]`. It reads
    row group by row group over HTTP, is resumable, and needs ~1 GB RAM. On the server
    `2025-01-01` takes ~40 min and 6.6 GB. The file has no row-group statistics, so every remote query
    is a full 45 GB scan.
- `markets.parquet` timestamps are in **milliseconds** (already fixed in `pmbt/markets.py`).
- **Outcomes: use `yes_won_x` / `resolved_x`, not `yes_won`.** About 30% of closed 2026 markets store
  near-certain prices like `['0.0005','0.9995']` instead of exact 1/0, and 50-50 resolutions pay 0.5.
- HF throttles repeated `hf://` passes from one IP (429). `pmbt/hfurl.py` resolves the signed CDN URL
  once.
- **UMA:** the challenge window after a proposal is 10 min to 2 h (**median 30 min** in 2026), not always
  2 h. On-chain contracts, adapters, conditionId rules and working RPCs: `research/uma_snipe/README.md` ("Gotchas").
- DuckDB ≥1.4 dropped `allow_asterisks_in_http_paths` (`pmbt/hfurl.prep` ignores it now).
- **Shared machine, many agents:** cap DuckDB memory and threads, use a private DuckDB temp dir per
  process, and never make duplicate copies of the tape.
