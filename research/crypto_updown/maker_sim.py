"""numba fill engine for maker replays (see idea31_maker.py docstring)."""
import numba

@numba.njit(cache=False)
def sim(tw, tsec, upx, dirn, sh, wfirst, wn, wstart, bid, ask, act_b, act_a, q, L, qshare, eps, out_w, out_t, out_side, out_px, out_sh, qlag=1):
    nf = 0; cur_w = -1; cur_t = -1; inv = 0.0; rb = 0.0; ra = 0.0
    for k in range(len(tw)):
        if nf >= len(out_w) - 1:
            break
        w = tw[k]
        if w != cur_w:
            cur_w = w; inv = 0.0; cur_t = -1
        td = tsec[k] - qlag  # decision tick (quote built from the book qlag seconds before the print's second)
        off = td - wstart[w]
        if off < 0 or off >= wn[w]:
            continue
        r = wfirst[w] + off
        if td != cur_t:
            cur_t = td; rb = q; ra = q
        if dirn[k] < 0 and act_b[r] and upx[k] < bid[r] - eps and rb > 0:
            f = min(rb, qshare * sh[k], L - inv)
            if f > 1e-9:
                rb -= f; inv += f
                out_w[nf] = w; out_t[nf] = td; out_side[nf] = 1; out_px[nf] = bid[r]; out_sh[nf] = f; nf += 1
        elif dirn[k] > 0 and act_a[r] and upx[k] > ask[r] + eps and ra > 0:
            f = min(ra, qshare * sh[k], L + inv)
            if f > 1e-9:
                ra -= f; inv -= f
                out_w[nf] = w; out_t[nf] = td; out_side[nf] = -1; out_px[nf] = ask[r]; out_sh[nf] = f; nf += 1
    return nf



def load_trades(con, coin, w, ali_m, EXT):
    """websocket trade prints within each kacho window, in Up-equivalent terms (upx, dirn: +1 taker buys Up-eq, -1 sells), ordered by window/time."""
    f = f"{EXT}/ali/ticks/{coin.upper()}_5-minute.parquet"
    con.register("wmap", w[["condition_id", "w", "start"]])
    con.register("amap", ali_m)
    return con.sql(f"""select wm.w::INT w, wm."start"::BIGINT AS "start", (timestamp_ms//1000)::BIGINT tsec, timestamp_ms ts,
            (case when outcome='Up' then price else 1-price end)::DOUBLE upx,
            (case when (outcome='Up') = (side='BUY') then 1 else -1 end)::INT dirn, (size_usdc/price)::DOUBLE sh
        from '{f}' t join amap a on t.market_id=a.market_id join wmap wm on a.condition_id=wm.condition_id
        where source='websocket' and price>0 and price<1 and timestamp_ms//1000 >= wm."start" and timestamp_ms//1000 < wm."start"+300
        order by w, ts""").df()
