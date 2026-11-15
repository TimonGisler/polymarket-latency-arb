"""#21c sub-second latency arb, BTC 5-minute, 2026-03-24..04-26.
Event: Binance BTCUSDT aggTrade at time T where the 1-s log return (vs last trade <= T-1000 ms) exceeds thr bp (cooldown 5 s).
Action: buy the side the jump favours. Fill = FIRST REAL Polymarket taker print on that side (aliplayer1 websocket trades, ms) at/after T+L
(L = 250/500/1000/2000 ms: 150 ms speed bump + network/compute), within 3 s; price = that print's price, size = min(print size, 100 sh).
Hold to official resolution; taker fee 0.07*p(1-p).  Also report the pre-event kacho mid (second T-1) and +10 s markout.
Chronological split: events before 2026-04-20 = in-sample (threshold choice), 04-20..04-26 = OOS."""
import numpy as np, pandas as pd, json, glob, zipfile, duckdb, sys
COIN = sys.argv[1] if len(sys.argv) > 1 else "btc"
from common import *
from maker_sim import load_trades
W = load_windows(); w = W[W.coin == COIN].reset_index(drop=True); w["w"] = np.arange(len(w))
start2w = dict(zip(w.start, w.w))
P = pd.read_parquet(f"{OUT}/panel_{COIN}.parquet", columns=["w", "t", "bu", "au"]); P["mid"] = ((P.bu + P.au) / 2).astype(np.float32); P = P.drop(columns=["bu", "au"])
isf = P.groupby("w").cumcount().to_numpy() == 0
first_idx = np.full(len(w), -1, np.int64); first_idx[P.w[isf].to_numpy()] = np.nonzero(isf)[0]
first_t = np.zeros(len(w), np.int64); first_t[P.w[isf].to_numpy()] = P.t[isf].to_numpy()
wn = np.bincount(P.w, minlength=len(w))
mid = P.mid.to_numpy()
def mid_at(wi, sec):
    off = sec - first_t[wi]
    return mid[first_idx[wi] + off] if 0 <= off < wn[wi] else np.nan
con = duckdb.connect(); con.execute("set threads=2; set memory_limit='3GB'; set enable_progress_bar=false")
ali_m = market_map()
tr = load_trades(con, COIN, w, ali_m, EXT)
tr = tr.sort_values("ts").reset_index(drop=True)
tts = tr.ts.to_numpy(); tw = tr.w.to_numpy(); tdir = tr.dirn.to_numpy(); tupx = tr.upx.to_numpy(); tsh = tr.sh.to_numpy()
rows = []
for f in sorted(glob.glob(f"{EXT}/binance_agg/{BINANCE[COIN]}-aggTrades-2026-0*.zip")):
    z = zipfile.ZipFile(f)
    b = pd.read_csv(z.open(z.namelist()[0]), header=None, usecols=[1, 5], names=["p", "ts"])
    ts = (b.ts.to_numpy() // 1000) if b.ts.iloc[0] > 1e14 else b.ts.to_numpy()
    p = b.p.to_numpy()
    j = np.searchsorted(ts, ts - 1000, side="right") - 1
    ok = j >= 0
    r = np.where(ok, np.log(p / p[np.clip(j, 0, None)]), 0) * 1e4
    for thr in (3, 5, 8, 12):
        cand = np.nonzero(np.abs(r) >= thr)[0]
        last = -10**15
        for i in cand:
            if ts[i] - last < 5000:
                continue
            last = ts[i]
            T = int(ts[i]); sec = T // 1000; st = sec - sec % 300
            wi = start2w.get(st)
            if wi is None or st + 300 - sec < 10:
                continue
            side = 1 if r[i] > 0 else -1
            m0 = mid_at(wi, sec - 1); m10 = mid_at(wi, sec + 10)
            for L in (250, 500, 1000, 2000):
                k = np.searchsorted(tts, T + L)
                fill = None
                while k < len(tts) and tts[k] < T + L + 3000:
                    if tw[k] == wi and tdir[k] == side:
                        fill = k; break
                    k += 1
                if fill is None:
                    rows.append((thr, L, T, wi, side, r[i], m0, m10, np.nan, np.nan, 0.0)); continue
                px = tupx[fill] if side > 0 else 1 - tupx[fill]
                # worst same-side print within 1 s after T+L (we are behind faster arbs and get the next levels)
                kk = fill; worst = px
                while kk < len(tts) and tts[kk] < T + L + 1000:
                    if tw[kk] == wi and tdir[kk] == side:
                        worst = max(worst, tupx[kk] if side > 0 else 1 - tupx[kk])
                    kk += 1
                rows.append((thr, L, T, wi, side, r[i], m0, m10, px, worst, min(tsh[fill], 100.0)))
E = pd.DataFrame(rows, columns=["thr", "L", "T", "w", "side", "r_bp", "m0", "m10", "px", "px_worst", "sh"])
E["up"] = w.up.to_numpy()[E.w]; E["start"] = w.start.to_numpy()[E.w]
E["win"] = np.where(E.side > 0, E.up, 1 - E.up)
E["pre_fair"] = np.where(E.side > 0, E.m0, 1 - E.m0); E["mk10"] = np.where(E.side > 0, E.m10, 1 - E.m10)
CUT = pd.Timestamp("2026-04-12 15:00", tz="UTC").value // 10**6 if COIN == "btc" else E["T"].quantile(0.6); E["oos"] = E["T"] >= CUT
print("OOS from", pd.to_datetime(CUT, unit="ms"))
E.to_parquet(f"{OUT}/idea21c_events{'' if COIN == 'btc' else '_' + COIN}.parquet", index=False)
res = {}
def run(F, label, slip=0.0, worst=False):
    F = F.copy()
    F["px"] = (F.px_worst if worst else F.px) + slip
    F = F[(F.px < 0.99) & (F.px > 0.01)]
    F["fee"] = F.sh * fee_ps(F.px); F["cost"] = F.sh * F.px + F.fee; F["pnl"] = F.sh * (F.win - F.px) - F.fee
    F["cluster"] = F.start; F["t_entry"] = F["T"] // 1000; F["t_exit"] = F.start + 300; F["shares"] = F.sh; F["price"] = F.px
    for (thr, L, o), g in F.groupby(["thr", "L", "oos"]):
        s = summ(g); s["mean_px_minus_prefair"] = float((g.px - g.pre_fair).mean()); s["mean_mk10_minus_px"] = float((g.mk10 - g.px).mean())
        s["fill_rate"] = len(g) / max(1, len(E[(E.thr == thr) & (E.L == L) & (E.oos == o)]))
        res[f"{label}_thr{thr}_L{L}_{'oos' if o else 'is'}"] = s
        print(f"{label:>10} thr={thr:>2}bp L={L:>4}ms {'OOS' if o else 'IS '} fills={len(g):>5} fillrate={s['fill_rate']:.2f} px={g.px.mean():.3f} px-pre={s['mean_px_minus_prefair']:+.4f} "
              f"mk10-px={s['mean_mk10_minus_px']:+.4f} win={g.win.mean():.3f} ROI={s['roi']:+.4f} CI={np.round(s['roi_ci95'],4)} p={s['p_roi_le_0']:.3f} pnl/day={s['pnl_per_day']:.0f}")
    return F
base = E[E.px.notna()]
Fa = run(base, "first")
run(base, "first+1c", slip=0.01)
run(base, "worst1s", worst=True)
run(base, "worst1s+1c", slip=0.01, worst=True)
Fa["day"] = pd.to_datetime(Fa["T"], unit="ms").dt.strftime("%m-%d")
daily = Fa[(Fa.thr == 3) & (Fa.L == 500)].groupby("day").pnl.sum().round(1)
print("daily pnl thr3 L500 first-print:", daily.to_dict()); res["daily_thr3_L500"] = daily.to_dict()
json.dump(res, open(f"{OUT}/idea21c{'' if COIN == 'btc' else '_' + COIN}.json", "w"), indent=1, default=float)
