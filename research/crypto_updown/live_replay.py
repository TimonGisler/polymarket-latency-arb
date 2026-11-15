#!/usr/bin/env python3
"""Replay the #21c rule on the live forward recording (live_fwd.py), in TODAY's regime (fee 0.07, 150 ms taker delay, TWAP settlement).

Signal: a spot trade (Binance via data-stream.binance.vision, or Coinbase) whose 1-s log return (vs. the last trade >= 1 s earlier,
in exchange time) is >= thr bp; 5 s cooldown per coin. The decision happens at OUR LOCAL RECEIVE TIME of that trade (r_dec).
Execution: the order reaches Polymarket at r_dec + one-way latency, waits for the 150 ms taker delay, and matches against the book as it
stands then. We see that book state at local time r_dec + 150 ms + RTT (RTT = 2 x the median one-way PM ws lag measured in the file).
Variants add 300 / 500 ms extra latency. The book is rebuilt from the recorded PM 'book' snapshots + 'price_change' deltas (Up token; the
Down book is its mirror). Order = marketable limit at (decision-time best ask + 2c), size cap 100 / 25 shares, walking displayed depth;
only levels that still exist at execution time fill. Fee = shares*0.07*p*(1-p). Settled on the official gamma outcome.
Every window with >= 10 s to go is eligible (5m and 15m, BTC and ETH)."""
import os as _os; ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "../.."))  # project root
import gzip, json, glob, heapq, subprocess, sys, time, math, collections
import numpy as np, pandas as pd
sys.path.insert(0, ROOT)
sys.path.insert(0, ROOT + "/research/crypto_updown")
from pmbt.metrics import summarize

LIVE = ROOT + "/data/ext/crypto/live"
FEE = 0.07


def lines(stream):
    for f in sorted(glob.glob(f"{LIVE}/*_{stream}.jsonl.gz")):
        try:
            with gzip.open(f, "rt") as fh:
                for ln in fh:
                    try:
                        yield json.loads(ln)
                    except Exception:
                        continue
        except EOFError:  # file still being written
            continue


def gamma_outcomes(slugs):
    out = {}
    for i in range(0, len(slugs), 40):
        b = slugs[i:i + 40]
        url = "https://gamma-api.polymarket.com/markets?limit=100&closed=true&" + "&".join("slug=" + s for s in b)
        r = subprocess.run(["curl", "-sS", "-m", "30", "-A", "Mozilla/5.0", url], capture_output=True, text=True).stdout
        for m in json.loads(r):
            op = json.loads(m["outcomePrices"]) if m.get("outcomePrices") else None
            if op and float(op[0]) in (0.0, 1.0):
                out[m["slug"]] = float(op[0])
    return out


def spot_events(src, thr_list):
    """returns DataFrame of jump events: coin, r_dec (local recv ms), T (exchange ms), ret_bp, thr"""
    seq = collections.defaultdict(list)
    if src == "bn":
        for d in lines("bn"):
            seq[d[1][:3].lower()].append((d[2], d[0], d[3]))          # (T, r, p)
    else:
        for d in lines("cb"):
            T = int(pd.Timestamp(d[2]).value // 10**6)
            seq[d[1][:3].lower()].append((T, d[0], d[3]))
    ev = []
    for coin, s in seq.items():
        s.sort()
        T = np.array([x[0] for x in s]); R = np.array([x[1] for x in s]); Pp = np.array([x[2] for x in s])
        j = np.searchsorted(T, T - 1000, side="right") - 1
        ok = j >= 0
        ret = np.where(ok, np.log(Pp / Pp[np.clip(j, 0, None)]), 0) * 1e4
        for thr in thr_list:
            last = -10**15
            for i in np.nonzero(np.abs(ret) >= thr)[0]:
                if T[i] - last < 5000:
                    continue
                last = T[i]
                ev.append((coin, int(R[i]), int(T[i]), float(ret[i]), thr))
    return pd.DataFrame(ev, columns=["coin", "r_dec", "T", "ret_bp", "thr"]).sort_values("r_dec").reset_index(drop=True)


class Book:
    __slots__ = ("bids", "asks", "ts")

    def __init__(self):
        self.bids = {}; self.asks = {}; self.ts = 0

    def best_ask(self, side):
        """side +1: buy Up -> Up asks; side -1: buy Down -> 1 - Up bids"""
        if side > 0:
            return min(self.asks) if self.asks else None
        return 1 - max(self.bids) if self.bids else None

    def levels(self, side):
        if side > 0:
            return sorted(self.asks.items())
        return sorted(((round(1 - p, 4), s) for p, s in self.bids.items()))


def main(extra_list=(0, 300, 500), caps=(100, 25), thr_list=(2, 3, 5, 8), srcs=("bn", "cb")):
    meta = {}
    for d in lines("meta"):
        meta[d["slug"]] = d
    tok2 = {}
    for slug, m in meta.items():
        tok2[m["tokens"][0]] = (slug, +1); tok2[m["tokens"][1]] = (slug, -1)
    # pass 1: one-way lag (local recv - server timestamp) of pm messages
    lags = []
    for k, d in enumerate(lines("pm")):
        if "m" in d and k % 50 == 0:
            try:
                x = json.loads(d["m"]); x = x[0] if isinstance(x, list) else x
                lags.append(d["r"] - int(x["timestamp"]))
            except Exception:
                pass
        if len(lags) > 20000:
            break
    oneway = float(np.median(lags)); rtt = max(2 * oneway, 100.0)  # floor: 50 ms each way for a realistic non-colocated bot
    print(f"pm ws one-way lag median {oneway:.0f} ms (p10 {np.percentile(lags,10):.0f}, p90 {np.percentile(lags,90):.0f}) -> RTT assumed {rtt:.0f} ms")
    base_lat = 150 + rtt
    all_trades = []; obs = []
    for src in srcs:
        E = spot_events(src, thr_list)
        print(src, "events", len(E), E.groupby("thr").size().to_dict())
        # expand: each event -> each active market of that coin with >=10 s left, each latency variant
        books = {}
        pend = []  # heap of (exec_r, id, info)
        ei = 0; uid = 0; results = []; chk = [0, 0]
        evs = E.to_dict("records")
        for d in lines("pm"):
            r = d["r"]
            # decisions due
            while ei < len(evs) and evs[ei]["r_dec"] <= r:
                e = evs[ei]; ei += 1
                tsec = e["r_dec"] / 1000
                side = 1 if e["ret_bp"] > 0 else -1
                for slug, m in meta.items():
                    if not slug.startswith(e["coin"]) or not (m["start"] <= tsec < m["end"] - 10) or slug not in books:
                        continue
                    b = books[slug]; a0 = b.best_ask(side)
                    if a0 is None:
                        continue
                    mid0 = None
                    if b.asks and b.bids:
                        mid0 = (min(b.asks) + max(b.bids)) / 2
                    for off in (100, 250, 500, 1000, 2000, 5000):
                        uid += 1
                        heapq.heappush(pend, (e["r_dec"] + off, uid, dict(e, slug=slug, side=side, a0=a0, mid0=mid0, obs=off)))
                    for extra in extra_list:
                        uid += 1
                        heapq.heappush(pend, (e["r_dec"] + base_lat + extra, uid, dict(e, slug=slug, side=side, a0=a0, mid0=mid0, extra=extra,
                                                                                     tau=m["end"] - tsec, tf=slug.split("-")[2])))
            # executions due (against book state before applying this message)
            while pend and pend[0][0] <= r:
                _, _, info = heapq.heappop(pend)
                b = books.get(info["slug"])
                if b is None:
                    continue
                if "obs" in info:
                    if b.asks and b.bids and info["mid0"] is not None:
                        obs.append((src, info["thr"], info["coin"], info["obs"], info["side"] * ((min(b.asks) + max(b.bids)) / 2 - info["mid0"]),
                                    b.best_ask(info["side"]) - info["a0"]))
                    continue
                lim = info["a0"] + 0.02
                lv = b.levels(info["side"])
                for cap in caps:
                    need = cap; cost = 0.0; got = 0.0
                    for p, s in lv:
                        if p > lim + 1e-9 or need <= 0:
                            break
                        q = min(s, need); got += q; cost += q * p; need -= q
                    results.append(dict(info, cap=cap, filled=got, vwap=(cost / got) if got else np.nan, ask_exec=b.best_ask(info["side"])))
            if "m" not in d:
                continue
            try:
                msg = json.loads(d["m"])
            except Exception:
                continue
            for x in (msg if isinstance(msg, list) else [msg]):
                et = x.get("event_type")
                if et == "book":
                    t = tok2.get(x.get("asset_id"))
                    if t and t[1] > 0:
                        b = books.setdefault(t[0], Book())
                        b.bids = {float(l["price"]): float(l["size"]) for l in x["bids"] if float(l["size"]) > 0}
                        b.asks = {float(l["price"]): float(l["size"]) for l in x["asks"] if float(l["size"]) > 0}
                elif et == "price_change":
                    for pc in x.get("price_changes", []):
                        t = tok2.get(pc.get("asset_id"))
                        if not t or t[1] < 0 or t[0] not in books:
                            continue
                        b = books[t[0]]; p = float(pc["price"]); s = float(pc["size"])
                        book = b.bids if pc["side"] == "BUY" else b.asks
                        if s <= 0:
                            book.pop(p, None)
                        else:
                            book[p] = s
                        if "best_ask" in pc and b.asks and b.bids:
                            chk[0] += 1
                            if abs(min(b.asks) - float(pc["best_ask"])) > 1e-9 or abs(max(b.bids) - float(pc["best_bid"])) > 1e-9:
                                chk[1] += 1
        print(src, "book check: price_change best bid/ask mismatches", chk[1], "of", chk[0])
        R = pd.DataFrame(results)
        R["src"] = src
        all_trades.append(R)
    R = pd.concat(all_trades, ignore_index=True)
    O = pd.DataFrame(obs, columns=["src", "thr", "coin", "ms", "signed_mid_move", "ask_move"])
    lead = O.groupby(["src", "coin", "thr", "ms"]).agg(n=("ms", "size"), mid_move=("signed_mid_move", "mean"), ask_move=("ask_move", "mean")).round(4)
    print("Polymarket response after spot jumps (signed mid move in prob units, mean):"); print(lead.unstack("ms").to_string())
    ended = [s for s, m in meta.items() if m["end"] < time.time() - 120]
    outc = gamma_outcomes(sorted(set(R.slug) & set(ended)))
    R["up"] = R.slug.map(outc)
    R = R[R.up.notna() & (R.filled > 0)].copy()
    R["win"] = np.where(R.side > 0, R.up, 1 - R.up)
    R["price"] = R.vwap; R["shares"] = R.filled
    R["fee"] = R.shares * FEE * R.price * (1 - R.price)
    R["cost"] = R.shares * R.price + R.fee
    R["pnl"] = R.shares * (R.win - R.price) - R.fee
    R["cluster"] = R.slug.str.rsplit("-", n=1).str[1].astype(int) // 300
    R["t_entry"] = R.r_dec // 1000; R["t_exit"] = R.t_entry + R.tau
    R.to_parquet(f"{LIVE}/replay_trades.parquet", index=False)
    if not outc:
        print("no resolved windows yet"); return
    hours = (max(m["end"] for m in meta.values() if m["slug"] in outc) - min(m["start"] for m in meta.values() if m["slug"] in outc)) / 3600
    out = {"lead_lag": {f"{k}": v for k, v in lead.reset_index().astype(str).set_index(["src", "coin", "thr", "ms"]).to_dict("index").items()}, "hours_covered": hours, "rtt_ms_assumed": rtt, "base_latency_ms": base_lat, "n_resolved_windows": len(outc), "variants": []}
    for key, g in R.groupby(["src", "thr", "extra", "cap", "coin"]):
        s = summarize(g, split=False, n_boot=1000)
        row = dict(zip(["src", "thr", "extra_ms", "cap", "coin"], key), n=len(g), trades_per_hour=len(g) / hours, roi=s["roi"], ci=s["roi_ci95"],
                   p=s["p_roi_le_0"], pnl=s["total_pnl"], pnl_per_day=s["total_pnl"] / hours * 24, avg_px=float(g.price.mean()),
                   avg_fill_sh=float(g.shares.mean()), exec_minus_dec_ask=float((g.price - g.a0).mean()), win=float(g.win.mean()))
        out["variants"].append(row)
    V = pd.DataFrame(out["variants"])
    pd.set_option("display.width", 250)
    print(V.round(4).to_string())
    json.dump(out, open(ROOT + "/research/crypto_updown/out/live_replay.json", "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
