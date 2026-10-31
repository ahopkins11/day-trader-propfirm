#!/usr/bin/env python3
"""ProjectX / TopstepX bridge. RUN THIS ON YOUR OWN COMPUTER ONLY.

Topstep's Terms of Use prohibit trading from a VPS, VPN or remote server, and
that includes cloud sessions. Topstep also does not allow API trading on Live
Funded accounts: there, enter trades by hand on TopstepX.

Credentials come from environment variables, never from a chat or a file in
the repo:
  export PROJECTX_USERNAME="your TopstepX username"
  export PROJECTX_API_KEY="the key from TopstepX Settings > API"
  export PROJECTX_BASE_URL="https://api.topstepx.com"     # optional, the default

  python3 prop-broker/projectx.py accounts
  python3 prop-broker/projectx.py contract MES
  python3 prop-broker/projectx.py bars MES --days 60 --out trader/bars/MES.json   # for --offline replays
  python3 prop-broker/projectx.py place --index 1 --account-id 123              # DRY RUN: prints the request
  python3 prop-broker/projectx.py place --index 1 --account-id 123 --send       # asks you to type yes, then sends
  python3 prop-broker/projectx.py positions --account-id 123
  python3 prop-broker/projectx.py flatten --account-id 123 --contract-id CON.F.US.MES.Z26

place only sends a ticket that prop-risk PASSED and that you approved with
prop-broker/ticket.py confirm in the last 15 minutes, and it asks once more in
the terminal. Bracket orders need Auto OCO Brackets on in your TopstepX risk
settings. Test on a Practice account first: API orders are final.
"""
import datetime
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from propfirm import cli, clock, config, contracts, rules  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ticket as ticket_mod  # noqa: E402

BASE = os.environ.get("PROJECTX_BASE_URL", "https://api.topstepx.com").rstrip("/")
SIDE = {"long": 0, "short": 1}             # 0 = buy, 1 = sell
TYPE_LIMIT, TYPE_MARKET, TYPE_STOP = 1, 2, 4
UNIT_MINUTE = 2


class ProjectXError(Exception):
    pass


def post(path, body, token=None, opener=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with (opener or urllib.request.urlopen)(req, timeout=20) as r:
            doc = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ProjectXError("%s answered HTTP %d" % (path, e.code))
    except (urllib.error.URLError, OSError) as e:
        raise ProjectXError("could not reach %s: %s" % (BASE, getattr(e, "reason", e)))
    if doc.get("success") is False:
        raise ProjectXError("%s: error %s %s" % (path, doc.get("errorCode"), doc.get("errorMessage") or ""))
    return doc


def login():
    user, key = os.environ.get("PROJECTX_USERNAME"), os.environ.get("PROJECTX_API_KEY")
    if not user or not key:
        raise ProjectXError("set PROJECTX_USERNAME and PROJECTX_API_KEY in your terminal (never paste the key in a chat)")
    return post("/api/Auth/loginKey", {"userName": user, "apiKey": key})["token"]


def find_contract(token, symbol, live=False):
    root = contracts.spec(symbol)["symbol"]
    found = post("/api/Contract/search", {"searchText": root, "live": live}, token).get("contracts") or []
    exact = [c for c in found if (c.get("symbolId") or "").endswith("." + root) and c.get("activeContract", True)]
    if not exact:
        raise ProjectXError("no active %s contract found (got: %s)" % (root, ", ".join(c.get("id", "?") for c in found)))
    return exact[0]


def order_payload(o, account_id, contract_id, signed_ticks=False):
    """The /api/Order/place body: a market entry with stop and target brackets in ticks."""
    sl, tp = int(o["stop_ticks"]), int(o["target_ticks"])
    if signed_ticks and o["side"] == "long":
        sl = -sl
    if signed_ticks and o["side"] == "short":
        tp = -tp
    return {"accountId": int(account_id), "contractId": contract_id, "type": TYPE_MARKET,
            "side": SIDE[o["side"]], "size": int(o["contracts"]),
            "stopLossBracket": {"ticks": sl, "type": TYPE_STOP},
            "takeProfitBracket": {"ticks": tp, "type": TYPE_LIMIT},
            "customTag": "prop-%s-%s" % (o["symbol"], datetime.datetime.now().strftime("%H%M%S"))}


def ask_yes(text, reader=input):
    print(text)
    return reader('Type yes to send this order, anything else to stop: ').strip().lower() == "yes"


def cmd_place(a, now):
    doc = config.read_json(cli.out_path("orders.json")) or {"orders": []}
    if not (1 <= a.index <= len(doc["orders"])):
        raise ProjectXError("no order %d in trader/orders.json" % a.index)
    o = doc["orders"][a.index - 1]
    st, why = ticket_mod.status(o, a.index, config.read_json(cli.out_path("risk.json")), now)
    if st != "READY":
        raise ProjectXError("ticket %d is %s (%s)" % (a.index, st, why))
    if not ticket_mod.approved(o, now):
        raise ProjectXError("no yes for this exact ticket in the last %d minutes: run ticket.py confirm first"
                            % ticket_mod.APPROVAL_MINUTES)
    token = login() if (a.send or not a.contract_id) else None
    cid = a.contract_id or find_contract(token, o["symbol"])["id"]
    body = order_payload(o, a.account_id, cid, signed_ticks=a.signed_ticks)
    print(ticket_mod.ticket_text(o))
    print("POST %s/api/Order/place\n%s" % (BASE, json.dumps(body, indent=2)))
    if not a.send:
        print("DRY RUN: nothing sent. Add --send to send it.")
        return
    accts = post("/api/Account/search", {"onlyActiveAccounts": True}, token).get("accounts") or []
    acct = next((x for x in accts if int(x.get("id", -1)) == int(a.account_id)), None)
    if not acct:
        raise ProjectXError("account %s is not one of your active accounts" % a.account_id)
    if acct.get("canTrade") is False:
        raise ProjectXError("account %s (%s) cannot trade right now" % (a.account_id, acct.get("name")))
    if acct.get("simulated") is False:
        raise ProjectXError("account %s (%s) is not simulated: Topstep does not allow API trading on Live Funded "
                            "accounts. Enter it by hand." % (a.account_id, acct.get("name")))
    if not ask_yes("Account %s (%s), balance %s." % (acct.get("id"), acct.get("name"), acct.get("balance"))):
        print("stopped: nothing sent")
        return
    res = post("/api/Order/place", body, token)
    log = ticket_mod.load_log()
    log["log"].append({"event": "placed", "key": rules.order_key(o),
                       "index": a.index, "broker_id": res.get("orderId"), "at": now.strftime("%Y-%m-%d %H:%M:%S")})
    config.write_json(ticket_mod.log_path(), log)
    print("placed: order id %s. Check it on TopstepX now." % res.get("orderId"))


def main(argv=None):
    p = cli.parser("ProjectX / TopstepX bridge (your computer only)")
    p.add_argument("--now")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("accounts")
    c = sub.add_parser("contract")
    c.add_argument("symbol")
    b = sub.add_parser("bars")
    b.add_argument("symbol")
    b.add_argument("--days", type=int, default=60)
    b.add_argument("--out", required=True)
    pl = sub.add_parser("place")
    pl.add_argument("--index", type=int, required=True)
    pl.add_argument("--account-id", required=True)
    pl.add_argument("--contract-id")
    pl.add_argument("--send", action="store_true")
    pl.add_argument("--signed-ticks", action="store_true",
                    help="send the stop as negative ticks on a buy (if your API version wants signed brackets)")
    ps = sub.add_parser("positions")
    ps.add_argument("--account-id", required=True)
    fl = sub.add_parser("flatten")
    fl.add_argument("--account-id", required=True)
    fl.add_argument("--contract-id", required=True)
    a = p.parse_args(argv)
    now = clock.parse_now(a.now)
    if a.cmd == "place":
        return cmd_place(a, now)
    if not a.cmd:
        p.print_help()
        return
    token = login()
    if a.cmd == "accounts":
        for x in post("/api/Account/search", {"onlyActiveAccounts": True}, token).get("accounts") or []:
            print("  id %s  %s  balance %s  canTrade %s  simulated %s" % (
                x.get("id"), x.get("name"), x.get("balance"), x.get("canTrade"), x.get("simulated", "?")))
    elif a.cmd == "contract":
        x = find_contract(token, a.symbol)
        print("  %s  %s  tick %s = $%s" % (x.get("id"), x.get("name"), x.get("tickSize"), x.get("tickValue")))
    elif a.cmd == "bars":
        x = find_contract(token, a.symbol)
        end = datetime.datetime.utcnow()
        start = end - datetime.timedelta(days=a.days)
        doc = post("/api/History/retrieveBars", {
            "contractId": x["id"], "live": False,
            "startTime": start.isoformat(timespec="milliseconds") + "Z",
            "endTime": end.isoformat(timespec="milliseconds") + "Z",
            "unit": UNIT_MINUTE, "unitNumber": 5, "limit": 20000, "includePartialBar": False}, token)
        doc["contract"] = x.get("id")
        config.write_json(a.out, doc)
        print("wrote %d bars of %s to %s" % (len(doc.get("bars") or []), x.get("id"), a.out))
    elif a.cmd == "positions":
        for x in post("/api/Position/searchOpen", {"accountId": int(a.account_id)}, token).get("positions") or []:
            print("  %s  size %s  avg %s  type %s" % (x.get("contractId"), x.get("size"), x.get("averagePrice"), x.get("type")))
    elif a.cmd == "flatten":
        if ask_yes("Close the whole %s position on account %s at market." % (a.contract_id, a.account_id)):
            post("/api/Position/closeContract", {"accountId": int(a.account_id), "contractId": a.contract_id}, token)
            print("close sent. Check TopstepX.")
        else:
            print("stopped: nothing sent")


if __name__ == "__main__":
    try:
        main()
    except ProjectXError as e:
        cli.fail(str(e))
    except (ValueError, KeyError) as e:
        cli.fail(str(e))
