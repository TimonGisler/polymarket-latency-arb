#!/usr/bin/env python3
"""Why do real orders fill far less often than paper? (LOG 2026-11-19.)

For every real order of trader.py (data/trader/decisions.jsonl, ev "order" with a decision), rebuild the recorded BTC 5m
book (pmc stream, as live_replay.py) and ask: would 5 shares at the order's own limit have found depth
  * at fixed delays after we received the Binance trade (0 .. 3000 ms), and
  * at the moment the exchange answered us (sent + ack_ms), and halfway there?
If the paper fill rate falls to the real one (~26%) only at the answer time, our order lands late (Polymarket's side);
if it stays high even then, someone else takes the depth that the recorded book still shows us (or the book lags).

Run (pmbot image, needs pandas for the import):
  docker run --rm -m 512m --cpus 1 -v $PWD:/app -w /app pmbot python -u research/crypto_updown/fill_check.py
Writes research/crypto_updown/out/fill_check.json.
"""
import os, sys, glob, gzip, json, heapq, collections
sys.path.insert(0, os.path.dirname(__file__))
from live_replay import Book, LIVE, WIN, ROOT

FIXED = [0, 100, 250, 500, 750, 1000, 1500, 2000, 3000]
SIZE = 5

dec, orders = {}, []
for ln in open(ROOT + "/data/trader/decisions.jsonl"):
    e = json.loads(ln)
    if e["ev"] == "decision":
        dec[e["id"]] = e
    elif e["ev"] == "order" and e["id"] in dec:
        orders.append(e)
t_first = min(dec[o["id"]]["r"] for o in orders) - 60_000
hour0 = __import__("time").strftime("%Y%m%d_%H", __import__("time").gmtime(t_first / 1000))
fs = [f for f in sorted(glob.glob(f"{LIVE}/*_pmc.jsonl.gz")) if os.path.basename(f)[:11] >= hour0]

checks = []                       # (time ms, n, order index, label)
n = 0
for i, o in enumerate(orders):
    r = dec[o["id"]]["r"]
    for ms in FIXED:
        checks.append((r + ms, n, i, f"+{ms} ms")); n += 1
    checks.append((o["sent"] + o["ack_ms"] // 2, n, i, "half-way to answer")); n += 1
    checks.append((o["sent"] + o["ack_ms"], n, i, "at answer")); n += 1
heapq.heapify(checks)

res = collections.defaultdict(dict)   # order index -> label -> (shares, ask)
books = {}


def rows():
    for f in fs:
        try:
            with gzip.open(f, "rt") as fh:
                for ln in fh:
                    try:
                        yield json.loads(ln)
                    except ValueError:
                        continue
        except EOFError:
            pass


for d in rows():
    r = d[1]
    while checks and checks[0][0] <= r:                     # book as it was just before this row
        _, _, i, lab = heapq.heappop(checks)
        o = orders[i]; b = books.get(o["start"]); side = 1 if o["side"] == "Up" else -1
        res[i][lab] = (b.fill(side, o["limit"], SIZE)[0], b.ask(side)) if b is not None and b.ok else None
    kind, st = d[0], d[3]
    if kind == "c":
        b = books.setdefault(st, Book())
        p, s = float(d[4]), float(d[5]); sb = b.bids if d[6] == "B" else b.asks
        if s > 0:
            sb[p] = s
        else:
            sb.pop(p, None)
    elif kind == "b":
        b = books.setdefault(st, Book())
        b.bids = {float(p): float(s) for p, s in d[4] if float(s) > 0}
        b.asks = {float(p): float(s) for p, s in d[5] if float(s) > 0}
        b.ok = True
    elif kind in ("s", "e"):
        books[st] = Book()
    for old in [s for s in books if (s + WIN + 120) * 1000 < r]:
        del books[old]

labels = [f"+{ms} ms" for ms in FIXED] + ["half-way to answer", "at answer"]
real = [o["shares"] > 0 for o in orders]
out = {"orders": len(orders), "real_fill_rate": round(sum(real) / len(orders), 3), "rows": []}
print(f"{len(orders)} real orders, really filled {sum(real)} ({sum(real) / len(orders):.0%})")
print(f"{'book at':>20} {'n':>4} {'paper fill':>10} {'agree':>6} {'paper yes/real no':>18} {'paper no/real yes':>18}")
for lab in labels:
    v = [(res[i].get(lab), real[i]) for i in range(len(orders))]
    v = [(x[0] > 0, y) for x, y in v if x is not None]
    if not v:
        continue
    pf = sum(x for x, _ in v); ag = sum(x == y for x, y in v)
    yn = sum(x and not y for x, y in v); ny = sum(y and not x for x, y in v)
    print(f"{lab:>20} {len(v):>4} {pf / len(v):>10.0%} {ag / len(v):>6.0%} {yn:>18} {ny:>18}")
    out["rows"].append({"book_at": lab, "n": len(v), "paper_fill": round(pf / len(v), 3), "agree": round(ag / len(v), 3),
                        "paper_yes_real_no": yn, "paper_no_real_yes": ny})
json.dump(out, open(os.path.dirname(__file__) + "/out/fill_check.json", "w"), indent=1)
