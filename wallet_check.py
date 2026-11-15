#!/usr/bin/env python3
"""Read-only check of this project's wallet: addresses, cash per signature type, positions, open orders.
Places no orders and never prints the key. Run:
  docker run --rm --env-file .env.wallet -v "$PWD":/app:ro -w /app pmbot python wallet_check.py
(key: PK in .env.wallet, root-only, gitignored; the pmbot image has py_clob_client_v2.)
"""
import json, os, sys, urllib.request
from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import AssetType, BalanceAllowanceParams

CLOB = "https://clob.polymarket.com"
pk = os.environ.get("PK") or sys.exit("PK missing (--env-file .env.wallet)")
base = ClobClient(CLOB, 137, key=pk)
creds = base.create_or_derive_api_key()
print("API access: ok (credentials derived)")
print("signer (EOA):", base.get_address())
total = 0.0
for st, name in ((1, "Polymarket proxy"), (2, "safe"), (0, "plain EOA")):
    funder = base.get_address()
    if st:      # the server tells us the maker address for this signature type (as the LP bot's account.py does)
        base.creds = creds; base.mode = base._get_client_mode(); path = "/rewards/user/markets"
        r = base._get(f"{CLOB}{path}", headers=base._l2_headers("GET", path), params={"signature_type": st, "page_size": 1})
        funder = (r.get("data") or [{}])[0].get("maker_address")
    c = ClobClient(CLOB, 137, key=pk, creds=creds, signature_type=st, funder=funder)
    try:
        bal = c.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
        usd = float(bal.get("balance") or 0) / 1e6; total += usd
        allow = bal.get("allowances") or bal.get("allowance")
        ok = any(int(v) > 0 for v in allow.values()) if isinstance(allow, dict) else bool(allow and int(allow) > 0)
        print(f"signature_type={st} ({name}) address={funder} cash=${usd:.2f} trading allowance set: {ok}")
    except Exception as e:
        print(f"signature_type={st} ({name}) address={funder} balance call failed: {str(e)[:150]}")
        continue
    if funder:
        try:
            req = urllib.request.Request(f"https://data-api.polymarket.com/v2/positions?user={funder}&limit=500", headers={"User-Agent": "Mozilla/5.0"})
            pos = json.loads(urllib.request.urlopen(req, timeout=20).read())
            pos = pos.get("data", pos) if isinstance(pos, dict) else pos
            print(f"   positions: {len(pos)}")
        except Exception as e:
            print("   positions call failed:", str(e)[:120])
        try:
            oo = c.get_open_orders()
            print(f"   open orders: {len(oo.get('data', oo)) if isinstance(oo, dict) else len(oo)}")
        except Exception as e:
            print("   open orders call failed:", str(e)[:120])
print(f"total cash across the three: ${total:.2f}")
