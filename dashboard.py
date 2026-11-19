#!/usr/bin/env python3
"""Read-only status page for the latency-arb test: python dashboard.py (port 8080; stdlib only, holds no keys).

Shows whether the recorder works, and the docs as they are on disk, so the page keeps no copy of anything:
  * recorder: data/status.json (written every 10 s by research/crypto_updown/live_fwd.py) and the files in
    data/ext/crypto/live/;
  * real orders: data/trader/summary.json, a flat {label: value} object, once a trader writes it, and a chart of
    real vs paper profit from data/trader/decisions.jsonl;
  * text: README.md ("Where it stands", "Plan", "Needs the owner") and the newest entry of docs/LOG.md.
Served at https://latency.77-42-11-137.sslip.io by the LP bot's caddy, with the LP dashboard's login
(DASHBOARD_USER / DASHBOARD_PASSWORD in /root/polymarket-bot/.env); see docker-compose.yml.
"""
import base64, glob, html, json, os, re, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")
USER = os.environ.get("DASHBOARD_USER", "owner")
WANT = {"Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode(enc)).decode() for enc in ("utf-8", "latin-1")
        if enc == "utf-8" or all(ord(ch) < 256 for ch in USER + PASSWORD)}
CSS = """
:root{--bg:#fafafa;--fg:#1c1c1c;--dim:#666;--line:#ddd;--card:#fff;--ok:#1a7f37;--bad:#c62828;--warn:#9a6700;--s1:#2a78d6;--s2:#eb6834}
@media(prefers-color-scheme:dark){:root{--bg:#161616;--fg:#e6e6e6;--dim:#999;--line:#333;--card:#1f1f1f;--ok:#4cc26a;--bad:#ff6b6b;--warn:#e0b040;--s1:#3987e5;--s2:#d95926}}
.ax{fill:var(--dim);font-size:12px}.lbl{fill:var(--fg);font-size:12px}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;max-width:900px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
h3{font-size:15px;margin:16px 0 6px}.dim{color:var(--dim);font-size:13px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin-top:12px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.tile b{display:block;font-size:19px}.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}
.scroll{overflow-x:auto}table{border-collapse:collapse;font-size:14px;margin:8px 0}
td,th{border:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top}
code{background:var(--card);border:1px solid var(--line);border-radius:4px;padding:0 4px;font-size:13px}ul{padding-left:20px;margin:6px 0}
"""


def inline(t):
    t = html.escape(t, quote=False)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', t)
    return re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)      # links into the repo: text only


def md(text):
    """the little markdown the docs use: headings, bullets (with continuation lines), tables, paragraphs"""
    out, par, lst, tbl = [], [], [], []

    def flush():
        if par:
            out.append("<p>" + inline(" ".join(par)) + "</p>")
        if lst:
            out.append("<ul>" + "".join("<li>" + inline(x) + "</li>" for x in lst) + "</ul>")
        if tbl:
            rows = [[c.strip() for c in r.strip().strip("|").split("|")] for r in tbl if not re.match(r"^\s*\|[\s|:-]+\|\s*$", r)]
            body = "".join("<tr>" + "".join(f"<{'th' if i == 0 else 'td'}>{inline(c)}</{'th' if i == 0 else 'td'}>" for c in r) + "</tr>"
                           for i, r in enumerate(rows))
            out.append(f'<div class="scroll"><table>{body}</table></div>')
        par.clear(); lst.clear(); tbl.clear()

    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            flush()
        elif s.startswith("#"):
            flush(); out.append("<h3>" + inline(s.lstrip("# ")) + "</h3>")
        elif s.startswith("|"):
            if par or lst:
                flush()
            tbl.append(s)
        elif re.match(r"^[-*] ", s):
            if par or tbl:
                flush()
            lst.append(s[2:])
        elif lst:
            lst[-1] += " " + s
        else:
            if tbl:
                flush()
            par.append(s)
    flush()
    return "\n".join(out)


def section(path, heading):
    """the text under a '## heading' (prefix match), up to the next '## '"""
    try:
        t = open(os.path.join(ROOT, path)).read()
    except OSError:
        return ""
    m = re.search(r"^## " + re.escape(heading) + r".*?\n(.*?)(?=^## |\Z)", t, re.S | re.M)
    return m.group(1) if m else ""


def tile(label, value, cls="", note=""):
    return f'<div class="tile"><span class="dim">{label}</span><b class="{cls}">{value}</b><span class="dim">{note}</span></div>'


def ago(sec):
    return f"{sec:.0f} s" if sec < 120 else f"{sec / 60:.0f} min" if sec < 7200 else f"{sec / 3600:.1f} h" if sec < 172800 else f"{sec / 86400:.1f} d"


def money_view():
    """Plain-words headline + SVG chart of real-money PnL against the paper fills of the same signals, from the
    trader's log (data/trader/decisions.jsonl). Both counted when the 5-minute window settles."""
    dec, ex, orders, up_won = {}, {}, [], {}
    try:
        for ln in open(ROOT + "/data/trader/decisions.jsonl"):
            try:
                e = json.loads(ln)
            except ValueError:
                continue
            if e["ev"] == "decision":
                dec[e["id"]] = e
            elif e["ev"] == "exec":
                ex[e["id"]] = e
            elif e["ev"] == "order":
                orders.append(e)
            elif e["ev"] == "settled":
                up_won[e["start"]] = e["up_won"]
    except OSError:
        return ""
    live = [o for o in orders if o["id"] in dec]          # leaves out the manual test order
    if not live:
        return ""
    t0 = min(o["sent"] for o in live) / 1000
    real, paper = [], []                                  # (settle time s, pnl $)
    for o in orders:
        if o["shares"] > 0 and o["start"] in up_won:
            w = up_won[o["start"]] if o["side"] == "Up" else 1 - up_won[o["start"]]
            real.append((o["start"] + 300, o["shares"] * w - o["paid"]))
    n_paper_fill = 0
    for o in live:                                        # paper on exactly the signals that got a real order
        d, x = dec[o["id"]], ex.get(o["id"])
        if not x or x.get("shares5", 0) <= 0:
            continue
        n_paper_fill += 1
        if d["start"] in up_won:
            w = up_won[d["start"]] if d["side"] == "Up" else 1 - up_won[d["start"]]
            sh, c = x["shares5"], x["cost5"]; p = c / sh
            paper.append((d["start"] + 300, sh * w - c - sh * 0.07 * p * (1 - p)))
    filled = sum(o["shares"] > 0 for o in live)
    rpnl = sum(v for _, v in real); ppnl = sum(v for _, v in paper)
    rcost = sum(o["paid"] for o in orders if o["shares"] > 0 and o["start"] in up_won)
    cls = "ok" if rpnl > 0 else "bad"
    head = (f'<p style="font-size:17px">Real money so far: <b class="{cls}">{rpnl:+.2f} $</b> on {len(real)} settled real trades'
            f'{f" ({rpnl / rcost:+.1%} on ${rcost:.0f} spent)" if rcost else ""}, since '
            f'{time.strftime("%m-%d %H:%M", time.gmtime(t0))} UTC. '
            f'Of {len(live)} real orders, <b>{filled} filled ({filled / len(live):.0%})</b>; on the same signals the paper '
            f'trader would have filled {n_paper_fill} ({n_paper_fill / len(live):.0%}) and made <b>{ppnl:+.2f} $</b>. '
            f'Loss cap: $30.</p>')
    # chart: cumulative $ over time, two series, one axis
    W, H_, L, R, T, B = 860, 260, 52, 70, 12, 28
    series = [("Real orders", "var(--s1)", sorted(real)), ("Paper, same signals", "var(--s2)", sorted(paper))]
    cum = []
    for name, col, pts in series:
        acc, c = 0.0, [(t0, 0.0)]
        for t, v in pts:
            acc += v; c.append((t, acc))
        cum.append((name, col, c))
    xs = [t for _, _, c in cum for t, _ in c] + [time.time()]
    ys = [v for _, _, c in cum for _, v in c] + [0.0]
    x0, x1 = min(xs), max(xs); y0, y1 = min(ys), max(ys)
    pad = (y1 - y0) * 0.08 or 1; y0 -= pad; y1 += pad
    X = lambda t: L + (t - x0) / ((x1 - x0) or 1) * (W - L - R)
    Y = lambda v: T + (y1 - v) / (y1 - y0) * (H_ - T - B)
    step = next(s for s in (0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000) if (y1 - y0) / s <= 6)
    g = []
    v = step * int(y0 / step)
    while v <= y1:
        if v >= y0:
            g.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--line)" '
                     f'stroke-width="{1.5 if v == 0 else 1}"/><text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end" '
                     f'class="ax">{"0" if abs(v) < 1e-9 else f"{v:+g}"} $</text>')
        v += step
    hours = (x1 - x0) / 3600; hs = next(h for h in (1, 2, 3, 6, 12, 24, 48) if hours / h <= 8)
    t = (int(x0 // 3600) + 1) * 3600
    while t <= x1:
        if t % (hs * 3600) == 0:
            g.append(f'<text x="{X(t):.1f}" y="{H_ - 8}" text-anchor="middle" class="ax">'
                     f'{time.strftime("%H:00" if t % 86400 else "%m-%d", time.gmtime(t))}</text>')
        t += 3600
    ly = [Y(c[-1][1]) for _, _, c in cum]
    if abs(ly[0] - ly[1]) < 14:                           # end labels would overlap: push them apart
        k = 1 if ly[0] >= ly[1] else -1; m = (ly[0] + ly[1]) / 2; ly = [m + 7 * k, m - 7 * k]
    for (name, col, c), lyy in zip(cum, ly):
        d = " ".join(f"{'M' if k == 0 else 'L'}{X(a):.1f},{Y(b):.1f}" for k, (a, b) in enumerate(c))
        g.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="2" stroke-linejoin="round"/>')
        a, b = c[-1]
        g.append(f'<circle cx="{X(a):.1f}" cy="{Y(b):.1f}" r="4" fill="{col}" stroke="var(--card)" stroke-width="2"/>'
                 f'<text x="{X(a) + 8:.1f}" y="{lyy + 4:.1f}" class="lbl">{b:+.2f} $</text>')
        for a, b in c[1:]:                                # hover: time and running total
            g.append(f'<circle cx="{X(a):.1f}" cy="{Y(b):.1f}" r="6" fill="transparent"><title>{name}, '
                     f'{time.strftime("%m-%d %H:%M", time.gmtime(a))} UTC: {b:+.2f} $</title></circle>')
    legend = " ".join(f'<span style="white-space:nowrap"><svg width="18" height="10"><line x1="0" x2="18" y1="5" y2="5" '
                      f'stroke="{col}" stroke-width="2"/></svg> {name}</span>&nbsp;&nbsp;' for name, col, _ in cum)
    svg = (f'<div class="dim">Cumulative profit in $, 5-share orders, counted when each 5-minute window settles. '
           f'Hover a point for its time.</div><div class="dim">{legend}</div>'
           f'<svg viewBox="0 0 {W} {H_}" style="width:100%;height:auto;background:var(--card);border:1px solid var(--line);'
           f'border-radius:8px" role="img" aria-label="Cumulative real and paper profit">{"".join(g)}</svg>')
    return head + svg


def page():
    now = time.time(); tiles = []
    try:
        st = json.load(open(ROOT + "/data/status.json"))
    except (OSError, ValueError):
        st = None
    if st is None:
        tiles.append(tile("Recorder", "no status file", "bad", "never ran, or data/ is gone"))
    else:
        age = now - st["t"] / 1000
        if age > 60:
            tiles.append(tile("Recorder", "NOT RUNNING", "bad", f"last sign of life {ago(age)} ago"))
        elif st.get("paused"):
            tiles.append(tile("Recorder", "PAUSED", "bad", "disk nearly full, not writing"))
        else:
            tiles.append(tile("Recorder", "recording", "ok", f"up {ago(now - st['started'] / 1000)}, checked {ago(age)} ago"))
        last = st.get("last", {})
        for name, key, t_of in (("Polymarket book", "pmc", lambda r: r[1]), ("Binance trades", "bn", lambda r: r[0])):
            r = last.get(key)
            if not r:
                tiles.append(tile(name, "no data yet", "warn")); continue
            a = now - t_of(r) / 1000
            if key == "pmc":
                left = r[3] + 300 - now
                val, note = f"Up {r[7]} / {r[8]}", f"bid / ask, window ends in {max(left, 0):.0f} s"
            else:
                val, note = f"${r[3]:,.0f}", f"arrives {st.get('bn_lag_ms')} ms after the trade (median)"
            tiles.append(tile(name, val, "ok" if a < 60 else "bad", note + ("" if a < 60 else f"; STALE, last {ago(a)} ago")))
        free = st["free_gb"]
        tiles.append(tile("Disk free", f"{free:.1f} GB", "ok" if free > 7.5 else "warn", "recorder pauses under 7.0"))
    files = glob.glob(ROOT + "/data/ext/crypto/live/*.jsonl.gz")
    if files:
        hours = sorted({os.path.basename(f)[:11] for f in files})
        first = time.strptime(hours[0] + "+0000", "%Y%m%d_%H%z")
        tiles.append(tile("Recorded so far", f"{len(hours)} h", "", f"since {time.strftime('%m-%d %H:00', first)} UTC, "
                                                                     f"{sum(os.path.getsize(f) for f in files) / 1e6:.0f} MB"))
    try:
        tr = json.load(open(ROOT + "/data/trader/summary.json"))
        trader = '<div class="scroll"><table>' + "".join(f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(str(v))}</td></tr>" for k, v in tr.items()) + "</table></div>"
    except (OSError, ValueError):
        trader = '<p class="dim">Not started. No real or paper orders have been placed yet (plan steps 3 and 4).</p>'
    log = ""
    try:
        log = re.split(r"^## ", open(ROOT + "/docs/LOG.md").read(), flags=re.M)[-1]
        log = "<h3>" + inline(log.split("\n", 1)[0]) + "</h3>" + md(log.split("\n", 1)[1])
    except (OSError, IndexError):
        pass
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="30"><title>Latency arb</title><style>{CSS}</style></head><body>
<h1>BTC latency arb: one-week test</h1><div class="dim">{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())} UTC, reloads every 30 s</div>
<div class="tiles">{''.join(tiles)}</div>
<h2>How the real money is doing</h2>{money_view()}
<h2>Needs you</h2>{md(section('README.md', 'Needs the owner'))}
<h2>Where it stands</h2>{md(section('README.md', 'Where it stands'))}
<h2>Plan</h2>{md(section('README.md', 'Plan'))}
<h2>Orders</h2>{trader}
<h2>Latest log entry</h2>{log}
</body></html>"""


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if PASSWORD and self.headers.get("Authorization") not in WANT:
            self.send_response(401); self.send_header("WWW-Authenticate", 'Basic realm="latency"'); self.end_headers(); return
        try:
            body, code = page().encode(), 200
        except Exception as e:      # a broken doc must not take the page down silently
            body, code = f"dashboard error: {e!r}".encode(), 500
        self.send_response(code); self.send_header("Content-Type", "text/html; charset=utf-8" if code == 200 else "text/plain")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), H).serve_forever()
