#!/usr/bin/env python3
"""The fixed #21c test (README "The test", fixed 2026-11-15) on the compact recording `pmc` of live_fwd.py.

Rule: Binance BTCUSDT trade whose log return vs. the last trade >= 1 s earlier (exchange time) is >= 3 bp; 5 s cooldown
(exchange time); decision at OUR receive time r of that trade; only the BTC 5m window running then, with more than 60 s left.
Buy the side the move favours: marketable limit at (best ask seen at r) + 2c, at most 100 shares, walking the displayed
depth of the book as we see it locally at r + 250 ms (150 ms taker delay + 100 ms round trip/compute; local receive time
throughout, so no clock sync with Polymarket is needed). Fee shares*0.07*p*(1-p); settled on the official gamma outcome.
ROI on cost incl. fees, bootstrap clustered by window, one-sided p, per-day ROI.
Sensitivity rows (never the verdict): execution at 200 / 350 ms, threshold 5 bp, Coinbase as the signal.

Book: Up token only (Down = 1 - Up bids). 'b' replaces the book, 'c' sets one level, 's' (re)subscribe clears it until the
next 'b'. Levels further than 15c from the best bid/ask are not recorded, so a price is "known" only inside
[max(best_bid) - 0.15, min(best_ask) + 0.15] over all rows since the last snapshot; fills outside that range are counted
(`unknown_lvl`), and so are fills while the rebuilt best disagreed with the server's (`book_bad`). Diagnostics: rebuilt best bid/ask vs. the best the server reports with each change.

Run (needs numpy/pandas: the pmbot image; ~1 core, < 1 GB):
  docker run --rm -m 1g --cpus 1 -v $PWD:/app -w /app pmbot python -u research/crypto_updown/live_replay.py [--days 20261116,...] [--report]
Each UTC day is replayed on its own (~9 min per full day) into data/replay/<day>.parquet; by default every finished day not
yet replayed after it ended, then the report over all of them. Windows never cross midnight and decisions need > 60 s left, so the split loses
nothing except the 5 s cooldown at 00:00. Report: research/crypto_updown/out/live_replay.json, data/replay_trades.parquet
(fills with outcomes); outcomes cached in data/outcomes_btc5m.json.
"""
import os as _os; ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "../.."))  # project root
import argparse, array, collections, datetime, glob, gzip, heapq, json, sys, time, urllib.request
import numpy as np, pandas as pd
sys.path.insert(0, ROOT)
from pmbt.metrics import summarize

LIVE = ROOT + "/data/ext/crypto/live"
OUTD = ROOT + "/data/replay"   # one parquet (all decisions, fills, no outcomes) + diag json per replayed UTC day
FEE = 0.07
BAND = 0.15            # as in live_fwd.py
WIN = 300              # BTC 5m
MIN_LEFT = 60          # s left in the window at decision
CAP = 100              # shares
SLIP = 0.02            # limit = decision ask + 2c
COOLDOWN = 5000        # ms, exchange time
# (name, signal source, threshold bp, ms from our receipt of the trade to the book state we fill against)
VARIANTS = [("TEST", "bn", 3, 250), ("sens exec 200 ms", "bn", 3, 200), ("sens exec 350 ms", "bn", 3, 350),
            ("sens 5 bp", "bn", 5, 250), ("sens Coinbase", "cb", 3, 250)]


def files(stream, days):
    fs = sorted(glob.glob(f"{LIVE}/*_{stream}.jsonl.gz"))
    return [f for f in fs if not days or _os.path.basename(f)[:8] in days]


def lines(stream, days):
    for f in files(stream, days):
        try:
            with gzip.open(f, "rt") as fh:
                for ln in fh:
                    try:
                        yield json.loads(ln)
                    except ValueError:
                        continue
        except EOFError:   # the hour being written, or a restart-damaged file (scripts/fix_gz.py)
            print("short read:", f, flush=True)


def spot_events(src, thr_list, days):
    """BTC trades -> signal events [(r_dec, T, ret_bp, thr)]"""
    T = array.array("q"); R = array.array("q"); P = array.array("d")
    if src == "bn":
        for d in lines("bn", days):
            if d[1] == "BTCUSDT":
                R.append(d[0]); T.append(d[2]); P.append(d[3])
    else:
        for d in lines("cb", days):
            if d[1] == "BTC-USD":
                R.append(d[0]); P.append(d[3])
                T.append(int(datetime.datetime.fromisoformat(d[2].replace("Z", "+00:00")).timestamp() * 1000))
    T = np.frombuffer(T, dtype=np.int64); R = np.frombuffer(R, dtype=np.int64); P = np.frombuffer(P)
    o = np.argsort(T, kind="stable"); T, R, P = T[o], R[o], P[o]
    j = np.searchsorted(T, T - 1000, side="right") - 1
    ret = np.where(j >= 0, np.log(P / P[np.clip(j, 0, None)]), 0) * 1e4
    ev = []
    for thr in thr_list:
        last = -10**15
        for i in np.nonzero(np.abs(ret) >= thr)[0]:
            if T[i] - last < COOLDOWN:
                continue
            last = T[i]
            ev.append((int(R[i]), int(T[i]), float(ret[i]), thr))
    print(src, "trades", len(T), "events", collections.Counter(e[3] for e in ev), flush=True)
    return ev


class Book:
    __slots__ = ("bids", "asks", "lo", "hi", "ok", "bad")

    def __init__(self):
        self.bids = {}; self.asks = {}; self.lo = 0.0; self.hi = 1.0; self.ok = False; self.bad = False   # bad: best disagreed with the server at the last message

    def best(self):
        return (max(self.bids) if self.bids else 0.0), (min(self.asks) if self.asks else 1.0)

    def ask(self, side):
        """best ask of the side we buy: +1 Up -> Up asks; -1 Down -> 1 - Up bids"""
        if side > 0:
            return min(self.asks) if self.asks else None
        return round(1 - max(self.bids), 4) if self.bids else None

    def fill(self, side, lim, cap):
        """walk the side's asks up to lim; returns shares, cost, whether a level outside the known range was used"""
        if side > 0:
            lv = sorted((p, s, p > self.hi + 1e-9) for p, s in self.asks.items())
        else:
            lv = sorted((round(1 - p, 4), s, p < self.lo - 1e-9) for p, s in self.bids.items())
        got = cost = 0.0; unk = False
        for p, s, u in lv:
            if p > lim + 1e-9 or got >= cap:
                break
            q = min(s, cap - got); got += q; cost += q * p; unk |= u
        return got, cost, unk


def gamma_outcomes(starts):
    """window start -> 1.0 if Up won, 0.0 if Down; cached"""
    path = ROOT + "/data/outcomes_btc5m.json"
    cache = json.load(open(path)) if _os.path.exists(path) else {}
    need = [s for s in starts if str(s) not in cache]
    for i in range(0, len(need), 40):
        url = "https://gamma-api.polymarket.com/markets?limit=100&closed=true&" + "&".join(f"slug=btc-updown-5m-{s}" for s in need[i:i + 40])
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        for m in json.loads(urllib.request.urlopen(req, timeout=30).read()):
            op = json.loads(m["outcomePrices"]) if m.get("outcomePrices") else None
            outs = json.loads(m["outcomes"])
            if op and float(op[0]) in (0.0, 1.0):
                cache[m["slug"].rsplit("-", 1)[1]] = float(op[outs.index("Up")])
    json.dump(cache, open(path, "w"))
    return {s: cache[str(s)] for s in starts if str(s) in cache}


def main(days):
    srcs = sorted({v[1] for v in VARIANTS})
    ev = {s: spot_events(s, sorted({v[2] for v in VARIANTS if v[1] == s}), days) for s in srcs}
    dec = []   # (r_dec, variant index, T, ret)
    for k, (_, src, thr, _) in enumerate(VARIANTS):
        dec += [(r, k, T, ret) for r, T, ret, t in ev[src] if t == thr]
    dec.sort()
    books = {}; pend = []; trades = []; skipped = collections.Counter(); di = 0; uid = 0
    diag = collections.Counter(); prev = None   # prev: (message key, start, book, reported best bid, best ask)
    lags = []

    def check(p):   # rebuilt best vs. the server's best after a whole message
        _, st, b, rb, ra = p
        if not b.ok:
            diag["msg_nobook"] += 1; return
        bb, ba = b.best(); live = "live" if st * 1000 <= p[0][0] < (st + WIN) * 1000 else "other"
        diag[f"msg_{live}"] += 1
        b.bad = abs(bb - rb) > 1e-9 or abs(ba - ra) > 1e-9
        if b.bad:
            diag[f"msg_{live}_mismatch"] += 1
            kind = ("ask_phantom" if ba < ra - 1e-9 else "ask_missing" if ba > ra + 1e-9 else "") or \
                   ("bid_phantom" if bb > rb + 1e-9 else "bid_missing")
            diag[f"msg_{live}_{kind}"] += 1
            if not (b.lo - 1e-9 <= rb and ra <= b.hi + 1e-9):
                diag[f"msg_{live}_mismatch_outside_known"] += 1

    for d in lines("pmc", days):
        r = d[1]
        while di < len(dec) and dec[di][0] <= r:               # decisions due: book as seen at r_dec
            r_dec, k, T, ret = dec[di]; di += 1
            st = r_dec // 1000 // WIN * WIN; b = books.get(st)
            if (st + WIN) - r_dec / 1000 <= MIN_LEFT:
                skipped["<=60 s left"] += 1; continue
            if b is None or not b.ok:
                skipped["no book"] += 1; continue
            side = 1 if ret > 0 else -1; a0 = b.ask(side)
            if a0 is None:
                skipped["no ask"] += 1; continue
            uid += 1
            heapq.heappush(pend, (r_dec + VARIANTS[k][3], uid, (k, r_dec, T, ret, st, side, a0)))
        while pend and pend[0][0] <= r:                          # executions due: book before this row
            _, _, (k, r_dec, T, ret, st, side, a0) = heapq.heappop(pend)
            b = books.get(st)
            if b is None or not b.ok:
                skipped["no book at exec"] += 1; continue
            got, cost, unk = b.fill(side, a0 + SLIP, CAP)
            trades.append((k, r_dec, T, ret, st, side, a0, b.ask(side), got, cost, unk, b.bad))
        kind = d[0]; st = d[3]
        if kind == "c":
            key = (r, st, d[2])
            if prev and prev[0] != key:
                check(prev)
            b = books.get(st)
            if b is None:
                b = books[st] = Book()
            p = float(d[4]); s = float(d[5]); rb = float(d[7]); ra = float(d[8])
            side_book = b.bids if d[6] == "B" else b.asks
            if s > 0:
                side_book[p] = s
            else:
                side_book.pop(p, None)
            b.lo = max(b.lo, rb - BAND); b.hi = min(b.hi, ra + BAND)
            diag["rows_c"] += 1
            if b.ok:
                bb, ba = b.best()
                diag["rows_c_mismatch"] += abs(bb - rb) > 1e-9 or abs(ba - ra) > 1e-9
            prev = (key, st, b, rb, ra)
            if len(lags) < 200000 and diag["rows_c"] % 20 == 0:
                lags.append(-d[2])
            continue
        if prev:
            check(prev); prev = None
        if kind == "b":
            b = books.get(st)
            if b is None:
                b = books[st] = Book()
            if b.ok and st * 1000 <= r < (st + WIN) * 1000:
                diag["snap_live"] += 1
                bids = {float(p): float(s) for p, s in d[4] if float(s) > 0}
                asks = {float(p): float(s) for p, s in d[5] if float(s) > 0}
                if b.best() != ((max(bids) if bids else 0.0), (min(asks) if asks else 1.0)):
                    diag["snap_live_best_differs"] += 1
                b.bids, b.asks = bids, asks
            else:
                b.bids = {float(p): float(s) for p, s in d[4] if float(s) > 0}
                b.asks = {float(p): float(s) for p, s in d[5] if float(s) > 0}
            bb, ba = b.best(); b.lo = bb - BAND; b.hi = ba + BAND; b.ok = True; b.bad = False
        elif kind in ("s", "e"):
            books[st] = Book(); diag["resubscribe" if kind == "s" else "ws_error"] += 1
            if kind == "e":
                diag["ws_error_live"] += st * 1000 <= r < (st + WIN) * 1000
        for old in [s for s in books if (s + WIN + 120) * 1000 < r]:
            del books[old]
    if prev:
        check(prev)
    print("decisions skipped:", dict(skipped), flush=True)
    print("book diagnostics:", dict(diag), flush=True)

    X = pd.DataFrame(trades, columns=["k", "r_dec", "T", "ret_bp", "start", "side", "a0", "ask_exec", "shares", "fill_cost", "unknown_lvl", "book_bad"])
    X["variant"] = X.k.map(lambda k: VARIANTS[k][0])
    tag = "_".join(sorted(days))
    _os.makedirs(OUTD, exist_ok=True)
    X.drop(columns=["k"]).to_parquet(f"{OUTD}/{tag}.parquet", index=False)
    json.dump({"pmc_hour_files": len(files("pmc", days)), "complete": max(days) < time.strftime("%Y%m%d", time.gmtime()), "book_diag": dict(diag), "decisions_skipped": dict(skipped),
               "pm_ws_lag_ms_median": float(np.median(lags)) if lags else None}, open(f"{OUTD}/{tag}_diag.json", "w"), indent=1)


def report():
    """all replayed days in data/replay/ -> the test's table (TEST row = the verdict's replay part), per-day ROI"""
    parts = sorted(glob.glob(OUTD + "/*.parquet"))
    X = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    diags = {_os.path.basename(p)[:-10]: json.load(open(p)) for p in sorted(glob.glob(OUTD + "/*_diag.json"))}
    hours = sum(d["pmc_hour_files"] for d in diags.values())
    ended = sorted(set(X.start[(X.start + WIN + 120) < time.time()]))
    outc = gamma_outcomes(ended)
    X["up"] = X.start.map(outc)
    n_dec = X.groupby("variant").size()
    unres = X[X.up.isna()].groupby("variant").size()
    nofill = X[X.up.notna() & (X.shares <= 0)].groupby("variant").size()
    unk = X[X.unknown_lvl & (X.shares > 0)].groupby("variant").size()
    bad = X[X.book_bad & (X.shares > 0)].groupby("variant").size()
    F = X[X.up.notna() & (X.shares > 0)].copy()
    F["price"] = F.fill_cost / F.shares
    F["win"] = np.where(F.side > 0, F.up, 1 - F.up)
    F["fee"] = F.shares * FEE * F.price * (1 - F.price)
    F["cost"] = F.fill_cost + F.fee
    F["pnl"] = F.shares * F.win - F.cost
    F["cluster"] = F.start
    F["t_entry"] = F.r_dec / 1000; F["t_exit"] = F.start + WIN
    F["day"] = pd.to_datetime(F.r_dec, unit="ms").dt.strftime("%Y-%m-%d")
    F.to_parquet(ROOT + "/data/replay_trades.parquet", index=False)

    out = {"replayed": sorted(diags), "pmc_hour_files": hours, "n_resolved_windows": len(outc), "rows": [], "per_day": {},
           "diag": diags}
    for name, *_ in VARIANTS:
        g = F[F.variant == name]
        row = {"variant": name, "decisions": int(n_dec.get(name, 0)), "unresolved": int(unres.get(name, 0)),
               "no_fill": int(nofill.get(name, 0)), "fills": len(g), "fills_unknown_level": int(unk.get(name, 0)),
               "fills_book_disagreed": int(bad.get(name, 0))}
        if len(g):
            s = summarize(g, split=False, n_boot=2000)
            pdays = g.groupby("day").agg(n=("pnl", "size"), pnl=("pnl", "sum"), cost=("cost", "sum"))
            pdays["roi"] = pdays.pnl / pdays.cost
            row.update(roi=s["roi"], roi_ci95=s["roi_ci95"], p_one_sided=s["p_roi_le_0"], pnl=s["total_pnl"], cost=s["total_cost"],
                       windows=s["n_clusters"], days=len(pdays), days_positive=int((pdays.roi > 0).sum()),
                       avg_shares=float(g.shares.mean()), avg_price=float(g.price.mean()), avg_fee=float(g.fee.mean()),
                       win_rate=float(g.win.mean()), exec_minus_decision_ask=float((g.price - g.a0).mean()),
                       fills_per_hour=len(g) / max(hours, 1), pnl_per_day=s["total_pnl"] / max(hours, 1) * 24)
            out["per_day"][name] = pdays.round(4).to_dict("index")
        out["rows"].append(row)
    pd.set_option("display.width", 250)
    print("replayed:", out["replayed"], "hours:", hours, "resolved windows:", len(outc))
    print(pd.DataFrame(out["rows"]).round(4).to_string())
    for name, pdd in out["per_day"].items():
        print(name, {d: (v["n"], v["roi"]) for d, v in pdd.items()})
    json.dump(out, open(ROOT + "/research/crypto_updown/out/live_replay.json", "w"), indent=1, default=float)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", default="", help="comma-separated YYYYMMDD to (re)replay, each on its own; "
                    "default: every finished UTC day not yet replayed complete")
    ap.add_argument("--report", action="store_true", help="only combine what data/replay/ holds")
    a = ap.parse_args()
    if not a.report:
        today = time.strftime("%Y%m%d", time.gmtime())
        todo = [x for x in a.days.split(",") if x] or sorted(
            {_os.path.basename(f)[:8] for f in files("pmc", set())} - {today}
            - {_os.path.basename(p)[:8] for p in glob.glob(OUTD + "/*_diag.json") if json.load(open(p)).get("complete")})
        for day in todo:
            print("replaying", day, flush=True)
            main({day})
    report()
