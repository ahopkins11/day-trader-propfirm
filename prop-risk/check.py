#!/usr/bin/env python3
"""Prop Risk Manager: PASS or BLOCK every order against the firm's rules and
yours, and keep the account numbers those rules need.

  python3 prop-risk/check.py check                      # trader/orders.json -> trader/risk.json
  python3 prop-risk/check.py account show               # balance, trailing floor, room left today
  python3 prop-risk/check.py account set --balance 50250 [--eod-high 50400]
  python3 prop-risk/check.py account trade --pnl -137.50   # after a trade closes
  python3 prop-risk/check.py account trade --pnl -2.80 --result be   # a scratch: counts as a breakeven
  python3 prop-risk/check.py account eod [--balance 50112.50]   # after the session: moves the trailing high

Copy the real limits for your plan from your Topstep dashboard into
trader/config.json: the shipped numbers are examples.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from propfirm import cli, clock, config, rules  # noqa: E402


def run_check(cfg, st, now, orders):
    out = []
    for i, o in enumerate(orders, 1):
        r = rules.check(o, cfg, st, now)
        r.update(index=i, key=rules.order_key(o), symbol=o["symbol"], contracts=o["contracts"], side=o["side"])
        out.append(r)
    return {"checked_at": now.strftime("%Y-%m-%d %H:%M"), "results": out}


def show_account(cfg, st):
    acct = cfg["account"]
    rm = rules.room(cfg, st)
    print("%s %s (%s)" % (acct.get("firm", ""), acct.get("plan", ""), acct.get("stage", "")))
    print("  balance %s, end-of-day high %s" % (cli.money(float(st["balance"])), cli.money(float(st["eod_high"]))))
    print("  trailing max loss: the account ends at %s (%s below the balance)" % (
        cli.money(rules.floor(cfg, st)), cli.money(float(st["balance"]) - rules.floor(cfg, st))))
    print("  today %s: realized %s, %d trades%s" % (st["date"], cli.money(float(st["realized_today"])), st["trades_today"],
          (" (%s)" % ", ".join(st["results_today"])) if st.get("results_today") else ""))
    print("  room left today after your buffer: " + ", ".join("%s %s" % (k, cli.money(v)) for k, v in rm.items()))
    if acct.get("profit_target"):
        print("  profit target %s: %s to go" % (cli.money(float(acct["profit_target"])), cli.money(
            float(acct["starting_balance"]) + float(acct["profit_target"]) - float(st["balance"]))))


def main(argv=None):
    p = cli.parser("Check orders against prop firm rules")
    p.add_argument("--config")
    p.add_argument("--now")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("check")
    ac = sub.add_parser("account")
    ac.add_argument("action", choices=["show", "set", "trade", "eod", "reset"])
    ac.add_argument("--balance", type=float)
    ac.add_argument("--eod-high", type=float)
    ac.add_argument("--pnl", type=float)
    ac.add_argument("--result", choices=["win", "loss", "be"], help="override: a scratch with fees is still a breakeven")
    a = p.parse_args(argv)
    cfg = config.load(a.config)
    now = clock.parse_now(a.now)
    st = rules.load_state(cfg, now.date())
    if a.cmd == "account":
        if a.action == "reset":
            if os.path.exists(rules.state_path()):
                os.remove(rules.state_path())
            st = rules.load_state(cfg, now.date())
        elif a.action == "set":
            if a.balance is not None:
                st["balance"] = a.balance
            if a.eod_high is not None:
                st["eod_high"] = a.eod_high
            st["eod_high"] = max(float(st["eod_high"]), float(st["balance"])) if a.eod_high is None else st["eod_high"]
        elif a.action == "trade":
            if a.pnl is None:
                raise ValueError("account trade needs --pnl (negative for a loss)")
            rules.record_trade(st, a.pnl, cfg, result=a.result)
        elif a.action == "eod":
            rules.end_of_day(st, a.balance)
        if a.action != "show":
            rules.save_state(st)
        show_account(cfg, st)
        return
    if a.cmd != "check":
        p.print_help()
        return
    doc = config.read_json(cli.out_path("orders.json"))
    if not doc or not doc.get("orders"):
        raise ValueError("no trader/orders.json: run prop-budget/size.py --write first")
    res = run_check(cfg, st, now, doc["orders"])
    for r in res["results"]:
        print("order %d: %s %s %d %s, loss at stop %s" % (r["index"], r["verdict"], r["side"].upper(),
                                                          r["contracts"], r["symbol"], cli.money(r["loss_at_stop_usd"])))
        for why in r["reasons"]:
            print("  BLOCK " + why)
        for w in r["warnings"]:
            print("  note  " + w)
    config.write_json(cli.out_path("risk.json"), res)
    print("wrote trader/risk.json")
    if any(r["verdict"] == "BLOCK" for r in res["results"]):
        sys.exit(1)


if __name__ == "__main__":
    cli.run(main)
