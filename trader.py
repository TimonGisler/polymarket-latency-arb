#!/usr/bin/env python3
"""#21c in real time: the fixed test's rule (README "The test") on live Binance trades and the live Polymarket book.

PAPER MODE ONLY (plan step 3): no key, no orders. Each decision is logged, and 250 ms later (when our order would land)
the book is walked as the replay does: limit = decision ask + 2c, at most 100 shares, and also the 5-share minimum
order that step 4 will really send. Resolved windows are settled on the official gamma outcome.

Rule (same as research/crypto_updown/live_replay.py): Binance BTCUSDT trade whose log return vs. the last trade
>= 1 s earlier (exchange time) is >= 3 bp; 5 s cooldown (exchange time); decision at our receive time; the BTC 5m
window running then (local clock), only with more than 60 s left; buy the side the move favours (Down = 1 - Up bids).

Output: data/trader/decisions.jsonl (one line per decision, then one per execution with the same id),
data/trader/summary.json (flat {label: value}, shown by dashboard.py). Run: docker compose up -d trader
"""
import os as _os; ROOT = _os.path.abspath(_os.path.dirname(__file__))
import argparse, asyncio, collections, json, math, os, sys, time, urllib.request
import websockets

OUT = ROOT + "/data/trader"
PM_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
BN_WS = "wss://data-stream.binance.vision/ws/btcusdt@trade"
FEE = 0.07
WIN = 300
MIN_LEFT = 60          # s
THR_BP = 3.0
COOLDOWN = 5000        # ms, exchange time
EXEC_MS = 250          # 150 ms taker delay + 100 ms round trip/compute (README "The test")
SLIP = 0.02
CAP = 100              # shares, the test
LIVE_SIZE = 5          # shares, the minimum order step 4 sends


def now_ms():
    return int(time.time() * 1000)


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


class Book:
    """Up token's book; Down = mirror"""
    def __init__(self):
        self.bids = {}; self.asks = {}; self.ok = False

    def ask(self, side):
        if side > 0:
            return min(self.asks) if self.asks else None
        return round(1 - max(self.bids), 4) if self.bids else None

    def levels(self, side):
        if side > 0:
            return sorted(self.asks.items())
        return sorted((round(1 - p, 4), s) for p, s in self.bids.items())

    def fill(self, side, lim, cap):
        got = cost = 0.0
        for p, s in self.levels(side):
            if p > lim + 1e-9 or got >= cap:
                break
            q = min(s, cap - got); got += q; cost += q * p
        return got, cost


class Trader:
    def __init__(self):
        os.makedirs(OUT, exist_ok=True)
        self.log = open(OUT + "/decisions.jsonl", "a")
        self.books = {}            # window start -> Book
        self.markets = {}          # window start -> {"tokens", "up"}
        self.ticks = collections.deque()   # (T, price) of the last ~1 s of Binance trades
        self.last_sig = -10**15
        self.lag = collections.deque(maxlen=500)
        self.n = collections.Counter()
        self.started = now_ms()
        self.uid = 0
        self.fills = {}            # id -> (start, side, shares100, cost100, shares5, cost5) waiting for an outcome
        self.settled = {"n": 0, "pnl100": 0.0, "cost100": 0.0, "n5": 0, "pnl5": 0.0, "cost5": 0.0, "wins": 0}
        self.last_dec = None

    def write(self, rec):
        self.log.write(json.dumps(rec, separators=(",", ":")) + "\n"); self.log.flush()

    # --- Polymarket ---------------------------------------------------------------------------------------------
    def on_pm(self, st, msg):
        up = self.markets[st]["up"]; b = self.books.setdefault(st, Book())
        d = json.loads(msg)
        for e in (d if isinstance(d, list) else [d]):
            t = e.get("event_type")
            if t == "book" and e.get("asset_id") == up:
                b.bids = {float(l["price"]): float(l["size"]) for l in e["bids"] if float(l["size"]) > 0}
                b.asks = {float(l["price"]): float(l["size"]) for l in e["asks"] if float(l["size"]) > 0}
                b.ok = True
            elif t == "price_change":
                for c in e["price_changes"]:
                    if c["asset_id"] != up:
                        continue
                    side_book = b.bids if c["side"][0] == "B" else b.asks
                    p = float(c["price"]); s = float(c["size"])
                    if s > 0:
                        side_book[p] = s
                    else:
                        side_book.pop(p, None)

    async def pm_market(self, st):
        toks = self.markets[st]["tokens"]
        while time.time() < st + WIN + 30:
            try:
                async with websockets.connect(PM_WS, max_size=2 ** 24, ping_interval=None, open_timeout=15) as ws:
                    await ws.send(json.dumps({"assets_ids": toks, "type": "market"}))
                    self.books[st] = Book(); last_ping = time.time()
                    while time.time() < st + WIN + 30:
                        if time.time() - last_ping > 8:
                            await ws.send("PING"); last_ping = time.time()
                        try:
                            msg = await asyncio.wait_for(ws.recv(), 5)
                        except asyncio.TimeoutError:
                            continue
                        if msg != "PONG":
                            self.on_pm(st, msg)
            except Exception as e:
                self.n["pm_ws_errors"] += 1
                self.books[st] = Book()
                print("pm err", st, repr(e)[:150], flush=True); await asyncio.sleep(1)
        self.books.pop(st, None); self.markets.pop(st, None)

    async def discovery(self):
        while True:
            t = int(time.time()); s0 = t - t % WIN
            for s in (s0, s0 + WIN):
                if s in self.markets:
                    continue
                try:
                    mk = get_json(f"https://gamma-api.polymarket.com/markets?slug=btc-updown-5m-{s}")
                    if mk:
                        toks = json.loads(mk[0]["clobTokenIds"]); outs = json.loads(mk[0]["outcomes"])
                        self.markets[s] = {"tokens": toks, "up": toks[outs.index("Up")], "cond": mk[0]["conditionId"]}
                        asyncio.create_task(self.pm_market(s))
                except Exception as e:
                    print("discovery err", repr(e)[:150], flush=True)
            await asyncio.sleep(20)

    # --- Binance and the rule -----------------------------------------------------------------------------------
    async def binance(self):
        while True:
            try:
                async with websockets.connect(BN_WS, max_size=2 ** 22, open_timeout=15) as ws:
                    while True:
                        d = json.loads(await asyncio.wait_for(ws.recv(), 30))
                        self.on_trade(now_ms(), int(d["T"]), float(d["p"]))
            except Exception as e:
                self.n["bn_ws_errors"] += 1
                print("binance err", repr(e)[:150], flush=True); await asyncio.sleep(2)

    def on_trade(self, r, T, p):
        self.n["bn_trades"] += 1; self.lag.append(r - T)
        q = self.ticks
        while len(q) >= 2 and q[1][0] <= T - 1000:
            q.popleft()
        ref = q[0][1] if q and q[0][0] <= T - 1000 else None
        q.append((T, p))
        if ref is None:
            return
        ret = math.log(p / ref) * 1e4
        if abs(ret) < THR_BP or T - self.last_sig < COOLDOWN:
            return
        self.last_sig = T; self.n["signals"] += 1
        st = r // 1000 // WIN * WIN; left = st + WIN - r / 1000
        if left <= MIN_LEFT:
            self.n["skip <=60 s left"] += 1; return
        b = self.books.get(st)
        if b is None or not b.ok:
            self.n["skip no book"] += 1; return
        side = 1 if ret > 0 else -1; a0 = b.ask(side)
        if a0 is None:
            self.n["skip no ask"] += 1; return
        self.uid += 1; self.n["decisions"] += 1
        did = f"{self.started}-{self.uid}"
        rec = {"id": did, "ev": "decision", "r": r, "T": T, "ret_bp": round(ret, 2), "start": st, "left_s": round(left, 1),
               "side": "Up" if side > 0 else "Down", "ask": a0, "limit": round(a0 + SLIP, 4), "levels": b.levels(side)[:5]}
        self.write(rec); self.last_dec = rec
        asyncio.get_running_loop().call_later(max(0, r + EXEC_MS - now_ms()) / 1000, self.execute, did, r, st, side, a0)

    def execute(self, did, r, st, side, a0):
        b = self.books.get(st)
        if b is None or not b.ok:
            self.n["no book at exec"] += 1; self.write({"id": did, "ev": "exec", "r": now_ms(), "book": False}); return
        lim = a0 + SLIP
        s100, c100 = b.fill(side, lim, CAP); s5, c5 = b.fill(side, lim, LIVE_SIZE)
        self.write({"id": did, "ev": "exec", "r": now_ms(), "late_ms": now_ms() - r - EXEC_MS, "ask": b.ask(side),
                    "shares": s100, "cost": round(c100, 4), "shares5": s5, "cost5": round(c5, 4), "levels": b.levels(side)[:5]})
        if s100 > 0:
            self.n["paper fills"] += 1; self.fills[did] = (st, side, s100, c100, s5, c5)
        else:
            self.n["no fill"] += 1

    # --- settlement and summary ---------------------------------------------------------------------------------
    async def settle(self):
        while True:
            await asyncio.sleep(60)
            due = sorted({f[0] for f in self.fills.values() if f[0] + WIN + 120 < time.time()})
            for s in due:
                try:
                    mk = get_json(f"https://gamma-api.polymarket.com/markets?closed=true&slug=btc-updown-5m-{s}")
                    op = json.loads(mk[0]["outcomePrices"]) if mk and mk[0].get("outcomePrices") else None
                    if not op or float(op[0]) not in (0.0, 1.0):
                        continue
                    up = float(op[json.loads(mk[0]["outcomes"]).index("Up")])
                except Exception as e:
                    print("settle err", repr(e)[:150], flush=True); continue
                for did in [k for k, f in self.fills.items() if f[0] == s]:
                    _, side, s100, c100, s5, c5 = self.fills.pop(did)
                    win = up if side > 0 else 1 - up
                    S = self.settled; S["n"] += 1; S["wins"] += win
                    for sh, c, k in ((s100, c100, ""), (s5, c5, "5")):
                        if sh <= 0:
                            continue
                        p = c / sh; cost = c + sh * FEE * p * (1 - p)
                        S["n5"] += k == "5"; S["pnl" + (k or "100")] += sh * win - cost; S["cost" + (k or "100")] += cost
                    self.write({"id": did, "ev": "settled", "start": s, "up_won": up, "win": win})

    async def summary(self):
        while True:
            await asyncio.sleep(10)
            S = self.settled; lag = sorted(self.lag)
            out = {"mode": "PAPER (no orders, no key)", "running since (UTC)": time.strftime("%Y-%m-%d %H:%M", time.gmtime(self.started / 1000)),
                   "updated (UTC)": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
                   "signals (>= 3 bp)": self.n["signals"], "decisions (> 60 s left, ask present)": self.n["decisions"],
                   "paper fills (<= 100 sh)": self.n["paper fills"], "no fill at limit": self.n["no fill"],
                   "settled fills": S["n"], "win rate": round(S["wins"] / S["n"], 3) if S["n"] else None,
                   "paper PnL 100 sh ($)": round(S["pnl100"], 2), "paper ROI 100 sh": f"{S['pnl100'] / S['cost100']:+.1%}" if S["cost100"] else None,
                   "paper PnL 5 sh ($)": round(S["pnl5"], 2), "paper ROI 5 sh": f"{S['pnl5'] / S['cost5']:+.1%}" if S["cost5"] else None,
                   "Binance lag median (ms)": lag[len(lag) // 2] if lag else None,
                   "last decision": (time.strftime("%H:%M:%S", time.gmtime(self.last_dec["r"] / 1000)) + f" {self.last_dec['side']} @ {self.last_dec['ask']}") if self.last_dec else None,
                   "skipped": {k: v for k, v in self.n.items() if k.startswith(("skip", "no book"))},
                   "ws errors (pm / bn)": f"{self.n['pm_ws_errors']} / {self.n['bn_ws_errors']}"}
            with open(OUT + "/summary.json.tmp", "w") as f:
                json.dump(out, f, indent=1)
            os.replace(OUT + "/summary.json.tmp", OUT + "/summary.json")

    async def run(self):
        await asyncio.gather(self.discovery(), self.binance(), self.settle(), self.summary())


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--live", action="store_true")
    if ap.parse_args().live:
        sys.exit("live orders are plan step 4 and not built yet")
    asyncio.run(Trader().run())
