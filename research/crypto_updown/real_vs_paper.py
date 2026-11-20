"""Real orders vs the paper trader on the same signals (half of the verdict, plan step 6).

Reads data/trader/decisions.jsonl (written by trader.py) and joins, by decision id, each real order ("order") with the
paper 5-share fill at 250 ms ("exec": shares5/cost5) and the outcome ("settled"). Reports fill rates, real and paper ROI
on cost incl. fees (bootstrap clustered by window, one-sided p for ROI > 0), the paper ROI split by what really happened
to the order (adverse selection), and per-day numbers. Writes research/crypto_updown/out/real_vs_paper.json.

  python3 research/crypto_updown/real_vs_paper.py      (stdlib only, a few seconds)
"""
import json, random, datetime as dt
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FEE = 0.07


def boot(rows, n=4000, seed=1):
    """rows: (window, pnl, cost). ROI on cost, 95% CI and one-sided p (ROI <= 0), resampling windows."""
    if not rows:
        return None
    by = defaultdict(lambda: [0.0, 0.0])
    for w, p, c in rows:
        by[w][0] += p; by[w][1] += c
    ws = list(by.values()); rnd = random.Random(seed); sims = []
    for _ in range(n):
        s = [ws[rnd.randrange(len(ws))] for _ in ws]
        sims.append(sum(x[0] for x in s) / sum(x[1] for x in s))
    sims.sort()
    P, C = sum(x[0] for x in ws), sum(x[1] for x in ws)
    return {"n": len(rows), "pnl": round(P, 2), "cost": round(C, 2), "roi": round(P / C, 4),
            "ci95": [round(sims[int(0.025 * n)], 4), round(sims[int(0.975 * n)], 4)],
            "p": round(sum(x <= 0 for x in sims) / n, 4)}


def main():
    ev = defaultdict(dict)
    for line in open(ROOT / "data/trader/decisions.jsonl"):
        e = json.loads(line)
        ev[e["id"]][e["ev"]] = e
    real, paper, paper_f, paper_k, days = [], [], [], [], defaultdict(lambda: defaultdict(list))
    n = {"orders": 0, "real_filled": 0, "real_killed": 0, "real_other": 0, "paper_filled": 0, "both_filled": 0}
    extra_c = []  # real minus paper $/share where both filled (fee incl.)
    for i, d in ev.items():
        o = d.get("order")
        if not o or i.startswith("manual"):
            continue
        n["orders"] += 1
        w = o["start"]; day = dt.datetime.fromtimestamp(o["sent"] / 1000, dt.timezone.utc).strftime("%Y-%m-%d")
        s = d.get("settled"); x = d.get("exec") or {}
        win = s["win"] if s else None
        rf = o.get("ok") and o.get("shares", 0) > 0
        n["real_filled" if rf else ("real_other" if o.get("unknown") or "no orders found" not in str(o.get("resp")) else "real_killed")] += 1
        sh5, c5 = x.get("shares5", 0) or 0, x.get("cost5", 0) or 0
        pf = sh5 > 0
        n["paper_filled"] += pf; n["both_filled"] += pf and rf
        if win is None:
            continue
        if rf:
            real.append((w, o["shares"] * win - o["paid"], o["paid"])); days[day]["real"].append(real[-1])
        if pf:
            p = c5 / sh5; cost = c5 + sh5 * FEE * p * (1 - p); r = (w, sh5 * win - cost, cost)
            paper.append(r); days[day]["paper"].append(r)
            (paper_f if rf else paper_k).append(r)
            if rf:
                extra_c.append(o["paid"] / o["shares"] - cost / sh5)
    out = {"made": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "counts": n,
           "real_fill_rate": round(n["real_filled"] / n["orders"], 3), "paper_fill_rate": round(n["paper_filled"] / n["orders"], 3),
           "real_minus_paper_c_per_share_both_filled": round(100 * sum(extra_c) / len(extra_c), 2) if extra_c else None,
           "real_settled": boot(real), "paper_same_signals": boot(paper),
           "paper_on_signals_real_filled": boot(paper_f), "paper_on_signals_real_killed": boot(paper_k),
           "per_day": {k: {"real": boot(v["real"]), "paper": boot(v["paper"])} for k, v in sorted(days.items())}}
    (ROOT / "research/crypto_updown/out/real_vs_paper.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "per_day"}, indent=1))
    for k, v in out["per_day"].items():
        print(k, "real", v["real"] and (v["real"]["n"], v["real"]["pnl"], v["real"]["roi"]), "paper", v["paper"] and (v["paper"]["n"], v["paper"]["pnl"], v["paper"]["roi"]))


if __name__ == "__main__":
    main()
