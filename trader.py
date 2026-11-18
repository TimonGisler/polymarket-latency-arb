#!/usr/bin/env python3
"""#21c in real time: the fixed test's rule (README "The test") on live Binance trades and the live Polymarket book.

Paper, always: each decision is logged, and 250 ms later (when our order would land) the book is walked as the replay
does: limit = decision ask + 2c, at most 100 shares, and also the 5-share order. Resolved windows settle on gamma.
--live (plan step 4, since 2026-11-18): also a real FAK buy of 5 shares at that limit, sent at decision time, with a
$30 loss cap that survives restarts (class Live). Needs PK (env_file .env.wallet), only in this container.

Rule (same as research/crypto_updown/live_replay.py): Binance BTCUSDT trade whose log return vs. the last trade
>= 1 s earlier (exchange time) is >= 3 bp; 5 s cooldown (exchange time); decision at our receive time; the BTC 5m
window running then (local clock), only with more than 60 s left; buy the side the move favours (Down = 1 - Up bids).

Output: data/trader/decisions.jsonl (one line per decision, then one per execution and per real order with the same id),
data/trader/summary.json (flat {label: value}, shown by dashboard.py). Run: docker compose up -d trader
"""
import os as _os; ROOT = _os.path.abspath(_os.path.dirname(__file__))
import argparse, asyncio, collections, concurrent.futures, json, math, os, sys, time, urllib.request
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
PROXY = "0xF82E76a7fDa4Df8ED7D88545B3180B7C20FE45C0"   # this project's wallet (README "Needs the owner"), signature_type=1
CLOB = "https://clob.polymarket.com"
LOSS_CAP = 30.0        # $ ever (owner 2026-11-15, docs/AUTOPILOT.md "Limits"): no order once paid - won + next order > this
MEM_MAX_MB = 100       # resident + swapped; it leaks like the recorder (~7 MB/h, LOG 2026-11-18): above this, exit
                       # cleanly in the last 60 s of a window and let docker restart it; state is rebuilt from the log


def now_ms():
    return int(time.time() * 1000)


def mem_mb():
    """this process's resident + swapped memory, MB"""
    try:
        kv = dict(l.split(":", 1) for l in open("/proc/self/status"))
        return sum(int(kv.get(k, "0 kB").split()[0]) for k in ("VmRSS", "VmSwap")) / 1024
    except Exception:
        return 0.0


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


class Live:
    """Real orders (plan step 4): FAK buy of LIVE_SIZE shares at the paper limit (ask + 2c), sent at decision time.
    Blocking SDK calls run in one worker thread, so the event loop keeps reading the books. Every order and the
    exchange's answer go to decisions.jsonl (ev "order"); the loss ledger is rebuilt from there, so the cap survives
    restarts. Polymarket redeems resolved winners itself (seen 2026-11-18); redeem() is the fallback, gasless as the LP
    bot's bot/positions.py does it."""
    def __init__(self):
        from py_clob_client_v2.client import ClobClient
        from py_clob_client_v2.clob_types import AssetType, BalanceAllowanceParams, OrderArgsV2, OrderType
        pk = os.environ.get("PK") or sys.exit("--live needs PK (env_file .env.wallet)")
        creds = ClobClient(CLOB, 137, key=pk).create_or_derive_api_key()
        self.c = ClobClient(CLOB, 137, key=pk, creds=creds, signature_type=1, funder=PROXY)
        self.Args, self.FAK = OrderArgsV2, OrderType.FAK
        self.bal = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        self.pool = concurrent.futures.ThreadPoolExecutor(1)    # orders only
        self.slow = concurrent.futures.ThreadPoolExecutor(1)    # warm-up, cash, redeem
        self.sc = None

    def warm(self, toks):
        """cache tick size, fee info and order version: signing one (unsent) order per token makes every HTTP call
        create_order needs, so a real order then only signs (first real order 2026-11-18: 116 ms signing cold)"""
        for t in toks:
            self.c.get_tick_size(t); self.c.get_fee_rate_bps(t); self.c.get_fee_exponent(t)
            self.c.create_order(self.Args(token_id=t, price=0.5, size=LIVE_SIZE, side="BUY"))

    def order(self, token, price, size):
        t0 = now_ms()
        try:
            o = self.c.create_order(self.Args(token_id=token, price=price, size=size, side="BUY")); t1 = now_ms()
            r = self.c.post_order(o, self.FAK)
        except Exception as e:   # a rejected order (HTTP 4xx) raises in the v2 SDK; it must never stop the trader
            t1 = t1 if "t1" in locals() else None
            r = {"success": False, "http": getattr(e, "status_code", None), "error": str(e)[:300]}
        return t0, t1, now_ms(), r

    def cash(self):
        return float(self.c.get_balance_allowance(self.bal).get("balance") or 0) / 1e6

    def redeem(self):
        """redeem every resolved winner of the wallet; returns [(condition, $)]"""
        from polymarket import BuilderApiKey, SecureClient
        pos = get_json(f"https://data-api.polymarket.com/v2/positions?user={PROXY}&limit=500")
        pos = pos.get("data", pos) if isinstance(pos, dict) else pos
        todo = {}
        for p in pos:   # v2 answers in snake_case; Polymarket itself redeemed our first winners within minutes (2026-11-18)
            v, c = float(p.get("current_value", p.get("currentValue")) or 0), p.get("condition_id", p.get("conditionId"))
            if p.get("redeemable") and v >= 0.005:
                todo[c] = todo.get(c, 0) + v
        if todo and self.sc is None:
            kf = ROOT + "/.env.builder"   # root-only, gitignored; never printed
            try:
                kv = dict(l.strip().split("=", 1) for l in open(kf) if "=" in l)
                key = BuilderApiKey(key=kv["BUILDER_KEY"], secret=kv["BUILDER_SECRET"], passphrase=kv["BUILDER_PASSPHRASE"])
            except (OSError, KeyError, ValueError):
                key = SecureClient.create(private_key=os.environ["PK"], wallet=PROXY).create_builder_api_key()
                with os.fdopen(os.open(kf, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
                    f.write(f"BUILDER_KEY={key.key}\nBUILDER_SECRET={key.secret}\nBUILDER_PASSPHRASE={key.passphrase}\n")
            self.sc = SecureClient.create(private_key=os.environ["PK"], wallet=PROXY, api_key=key)
        done = []
        for cond, v in todo.items():
            self.sc.redeem_positions(condition_id=cond).wait(); done.append((cond, round(v, 4)))
        return done


def order_amounts(r, price, size):
    """(shares, $ paid incl. fee, unknown) from the exchange's answer to a BUY. The fee comes on top of makingAmount, in
    cash (first order 2026-11-18: 5 @ 0.46 cost 2.3 + 0.08694). A 4xx rejection placed nothing. No answer (network,
    5xx) or one we can't read: unknown, and the loss cap counts it as paid in full at the limit."""
    if r.get("error") or r.get("success") is False:
        h = r.get("http")
        return (0.0, 0.0, False) if h and 400 <= h < 500 else (0.0, size * price, True)
    try:
        sh, usd = float(r.get("takingAmount") or 0), float(r.get("makingAmount") or 0)
        p = usd / sh if sh else 0.0
        return sh, usd + sh * FEE * p * (1 - p), False
    except (TypeError, ValueError):
        return 0.0, size * price, True


class Trader:
    def __init__(self, live=None):
        os.makedirs(OUT, exist_ok=True)
        self.live = live
        self.lfills = {}           # id -> (start, side, shares, paid, condition) real fills waiting for an outcome
        self.L = {"orders": 0, "filled": 0, "rejected": 0, "shares": 0.0, "paid": 0.0, "won": 0.0, "settled_paid": 0.0,
                  "ack_ms": collections.deque(maxlen=500), "redeemed": 0.0, "cash": None, "busy": False}
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
        self.since = self.started  # first logged decision (display); self.started stays unique per run (ids)
        self.reload()

    def reload(self):
        """rebuild counters, settled totals and unsettled fills from decisions.jsonl (survives restarts)"""
        dec, first = {}, None
        try:
            lines = open(OUT + "/decisions.jsonl")
        except FileNotFoundError:
            return
        for line in lines:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e["ev"] == "decision":
                dec[e["id"]] = e; self.n["decisions"] += 1; self.last_dec = e
                first = first or e["r"]
            elif e["ev"] == "exec" and e["id"] in dec:
                if e.get("shares", 0) > 0:
                    d = dec[e["id"]]; self.n["paper fills"] += 1
                    self.fills[e["id"]] = (d["start"], 1 if d["side"] == "Up" else -1, e["shares"], e["cost"], e["shares5"], e["cost5"])
                elif e.get("book", True):
                    self.n["no fill"] += 1
            elif e["ev"] == "order":
                self.book_order(e, dec.get(e["id"]))
            elif e["ev"] == "settled" and (e["id"] in self.fills or e["id"] in self.lfills):
                if e["id"] in self.fills:
                    self.book_settled(self.fills.pop(e["id"]), e["up_won"])
                if e["id"] in self.lfills:
                    self.book_live_settled(self.lfills.pop(e["id"]), e["up_won"])
            elif e["ev"] == "redeemed":
                self.L["redeemed"] += e["usd"]
        self.since = first or self.since
        print("reloaded", self.n["decisions"], "decisions,", len(self.fills), "unsettled fills", flush=True)

    def book_order(self, e, d):
        L = self.L; L["orders"] += 1
        if e.get("ack_ms") is not None:
            L["ack_ms"].append(e["ack_ms"])
        L["paid"] += e["paid"]
        if e["shares"] > 0:
            L["filled"] += 1; L["shares"] += e["shares"]
            self.lfills[e["id"]] = (e["start"], 1 if e["side"] == "Up" else -1, e["shares"], e["paid"], e["cond"])
        elif "no orders found to match" in str(e.get("resp")):   # FAK killed: nothing at or below our limit any more
            L["killed"] = L.get("killed", 0) + 1
        elif e.get("unknown"):
            L["unknown"] = L.get("unknown", 0) + 1
        elif not e.get("ok"):
            L["rejected"] += 1

    def book_live_settled(self, f, up):
        _, side, sh, paid, _ = f
        win = up if side > 0 else 1 - up
        self.L["won"] += sh * win; self.L["settled_paid"] += paid

    def net_loss(self):
        """$ paid for all real fills (settled or not) minus $ won: the cap counts open positions as lost"""
        return self.L["paid"] - self.L["won"]

    def book_settled(self, f, up):
        _, side, s100, c100, s5, c5 = f
        win = up if side > 0 else 1 - up
        S = self.settled; S["n"] += 1; S["wins"] += win
        for sh, c, k in ((s100, c100, ""), (s5, c5, "5")):
            if sh <= 0:
                continue
            p = c / sh; cost = c + sh * FEE * p * (1 - p)
            S["n5"] += k == "5"; S["pnl" + (k or "100")] += sh * win - cost; S["cost" + (k or "100")] += cost
        return win

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
                        if self.live:
                            asyncio.get_running_loop().run_in_executor(self.live.slow, self.live.warm, toks)
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
        if self.live:
            self.send(did, st, side, a0)
        asyncio.get_running_loop().call_later(max(0, r + EXEC_MS - now_ms()) / 1000, self.execute, did, r, st, side, a0)

    def send(self, did, st, side, a0):
        m = self.markets.get(st); price = round(min(a0 + SLIP, 0.99), 2)
        if m is None or self.L["busy"]:
            self.n["live skip (busy / no market)"] += 1; return
        if LIVE_SIZE * price < 1.0:   # the CLOB rejects marketable buys under $1 (seen 2026-11-18): 5 shares need a limit >= 0.20
            self.n["live skip (< $1 minimum)"] += 1; return
        if self.net_loss() + LIVE_SIZE * price * 1.1 > LOSS_CAP:
            self.n["live skip (loss cap)"] += 1; return
        token = m["up"] if side > 0 else [t for t in m["tokens"] if t != m["up"]][0]
        self.L["busy"] = True
        fut = asyncio.get_running_loop().run_in_executor(self.live.pool, self.live.order, token, price, LIVE_SIZE)

        def done(f):
            self.L["busy"] = False
            try:
                t0, t1, t2, r = f.result()
            except Exception as e:
                t0 = t1 = t2 = None; r = {"error": repr(e)[:300]}
            sh, paid, unknown = order_amounts(r if isinstance(r, dict) else {"error": str(r)[:300]}, price, LIVE_SIZE)
            rec = {"id": did, "ev": "order", "start": st, "side": "Up" if side > 0 else "Down", "cond": m["cond"], "limit": price,
                   "size": LIVE_SIZE, "sent": t0, "signed_ms": t1 - t0 if t1 else None, "ack_ms": t2 - t0 if t2 else None,
                   "ok": bool(isinstance(r, dict) and r.get("success") and not r.get("error")), "shares": sh, "paid": round(paid, 6), "unknown": unknown,
                   "resp": {k: v for k, v in (r.items() if isinstance(r, dict) else []) if k != "transactionsHashes"}}
            self.write(rec); self.book_order(rec, None)
            print("order", rec["side"], price, "->", sh, "sh $", round(paid, 4), rec["ack_ms"], "ms", str(rec["resp"])[:160], flush=True)
        fut.add_done_callback(done)   # runs in the event loop

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
            due = sorted({f[0] for f in list(self.fills.values()) + list(self.lfills.values()) if f[0] + WIN + 120 < time.time()})
            for s in due:
                try:
                    mk = get_json(f"https://gamma-api.polymarket.com/markets?closed=true&slug=btc-updown-5m-{s}")
                    op = json.loads(mk[0]["outcomePrices"]) if mk and mk[0].get("outcomePrices") else None
                    if not op or float(op[0]) not in (0.0, 1.0):
                        continue
                    up = float(op[json.loads(mk[0]["outcomes"]).index("Up")])
                except Exception as e:
                    print("settle err", repr(e)[:150], flush=True); continue
                for did in [k for k, f in self.lfills.items() if f[0] == s]:
                    f = self.lfills[did]; self.book_live_settled(self.lfills.pop(did), up)
                    if did not in self.fills:   # else the paper fill's line below settles both
                        self.write({"id": did, "ev": "settled", "start": s, "up_won": up, "win": up if f[1] > 0 else 1 - up})
                for did in [k for k, f in self.fills.items() if f[0] == s]:
                    win = self.book_settled(self.fills.pop(did), up)
                    self.write({"id": did, "ev": "settled", "start": s, "up_won": up, "win": win})

    async def upkeep(self):
        """live only: wallet cash every minute, redeem resolved winners every 5 minutes"""
        loop, k = asyncio.get_running_loop(), 0
        while True:
            try:
                self.L["cash"] = await loop.run_in_executor(self.live.slow, self.live.cash)
                if k % 5 == 0:
                    for cond, usd in await loop.run_in_executor(self.live.slow, self.live.redeem):
                        self.L["redeemed"] += usd; self.write({"ev": "redeemed", "r": now_ms(), "cond": cond, "usd": usd})
                        print("redeemed", cond[:12], usd, flush=True)
            except Exception as e:
                print("upkeep err", repr(e)[:200], flush=True)
            k += 1; await asyncio.sleep(60)

    async def summary(self):
        while True:
            await asyncio.sleep(10)
            S = self.settled; lag = sorted(self.lag)
            L = self.L; ack = sorted(L["ack_ms"])
            out = {"mode": f"LIVE: {LIVE_SIZE}-share orders, ${LOSS_CAP:.0f} loss cap" if self.live else "PAPER (no orders, no key)", "running since (UTC)": time.strftime("%Y-%m-%d %H:%M", time.gmtime(self.since / 1000)),
                   "last restart (UTC)": time.strftime("%Y-%m-%d %H:%M", time.gmtime(self.started / 1000)),
                   "updated (UTC)": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
                   "signals since restart (>= 3 bp)": self.n["signals"], "decisions (> 60 s left, ask present)": self.n["decisions"],
                   "paper fills (<= 100 sh)": self.n["paper fills"], "no fill at limit": self.n["no fill"],
                   "settled fills": S["n"], "win rate": round(S["wins"] / S["n"], 3) if S["n"] else None,
                   "paper PnL 100 sh ($)": round(S["pnl100"], 2), "paper ROI 100 sh": f"{S['pnl100'] / S['cost100']:+.1%}" if S["cost100"] else None,
                   "paper PnL 5 sh ($)": round(S["pnl5"], 2), "paper ROI 5 sh": f"{S['pnl5'] / S['cost5']:+.1%}" if S["cost5"] else None,
                   "Binance lag median (ms)": lag[len(lag) // 2] if lag else None,
                   "last decision": (time.strftime("%H:%M:%S", time.gmtime(self.last_dec["r"] / 1000)) + f" {self.last_dec['side']} @ {self.last_dec['ask']}") if self.last_dec else None,
                   "skipped": {k: v for k, v in self.n.items() if k.startswith(("skip", "no book"))},
                   "ws errors since restart (pm / bn)": f"{self.n['pm_ws_errors']} / {self.n['bn_ws_errors']}"}
            if self.live or L["orders"]:
                out.update({"REAL orders sent": L["orders"], "real orders filled": L["filled"],
                            "real killed (nothing at limit)": L.get("killed", 0), "real rejected": L["rejected"],
                            "real unknown answer": L.get("unknown", 0), "real shares bought": round(L["shares"], 2),
                            "real $ paid": round(L["paid"], 2), "real $ won (settled)": round(L["won"], 2),
                            "real net loss vs cap ($)": f"{self.net_loss():.2f} / {LOSS_CAP:.0f}",
                            "real PnL settled ($)": round(L["won"] - L["settled_paid"], 2), "redeemed ($)": round(L["redeemed"], 2),
                            "order ack median (ms)": ack[len(ack) // 2] if ack else None, "wallet cash ($)": L["cash"],
                            "live skips": {k: v for k, v in self.n.items() if k.startswith("live skip")}})
            with open(OUT + "/summary.json.tmp", "w") as f:
                json.dump(out, f, indent=1)
            os.replace(OUT + "/summary.json.tmp", OUT + "/summary.json")
            mem = mem_mb()
            if mem > MEM_MAX_MB and 240 <= time.time() % 300 < 290:   # last 60 s of a window: no decisions, no pending execs
                print(time.strftime("%m-%d %H:%M:%S"), f"memory {mem:.0f} MB > {MEM_MAX_MB}: clean exit, docker restarts", flush=True)
                self.log.close(); os._exit(0)

    async def run(self):
        await asyncio.gather(self.discovery(), self.binance(), self.settle(), self.summary(), *([self.upkeep()] if self.live else []))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--live", action="store_true")
    asyncio.run(Trader(Live() if ap.parse_args().live else None).run())
