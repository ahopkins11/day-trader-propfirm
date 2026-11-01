#!/usr/bin/env python3
"""Prop Order Ticket: shows each order in plain words and records your yes.
It never talks to a broker. Only prop-broker/projectx.py sends anything, and
only for a ticket that risk PASSED and you said yes to in the last 15 minutes.

  python3 prop-broker/ticket.py show
  python3 prop-broker/ticket.py confirm --index 1 --reply "yes"
  python3 prop-broker/ticket.py result --index 1 --status filled --broker-id 9056 --filled-price 6712.75
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from propfirm import cli, clock, config, contracts, rules  # noqa: E402

APPROVAL_MINUTES = 15


def log_path():
    return os.path.join(config.trader_dir(), "state", "broker.json")


def load_log():
    return config.read_json(log_path(), {"log": []})


def ticket_text(o):
    s = contracts.spec(o["symbol"])
    f = lambda x: contracts.fmt_price(x, s)  # noqa: E731
    act = "BUY" if o["side"] == "long" else "SELL"
    return ("%s %d %s at market, with a stop at %s (%d ticks) and a target at %s (%d ticks). "
            "If the stop fills at its price you lose about %s; at the target you make about %s. "
            "Flat by %s ET either way.%s" % (act, o["contracts"], o["symbol"], f(o["stop"]), o["stop_ticks"],
                                          f(o["target"]), o["target_ticks"], cli.money(o["loss_at_stop_usd"]),
                                          cli.money(o["gain_at_target_usd"]), o["flat_by"],
                                          (" Move the stop to %s by hand once price touches %s." % (f(o["entry"]), f(o["breakeven"])))
                                          if o.get("breakeven") is not None else ""))


def status(o, i, risk, now):
    r = next((x for x in (risk or {}).get("results", []) if x["index"] == i), None)
    if not r or r["key"] != rules.order_key(o):
        return "NOT CHECKED", "run prop-risk/check.py check first"
    if not (risk.get("checked_at") or "").startswith(now.date().isoformat()):
        return "STALE", "the risk check is from another day"
    if r["verdict"] != "PASS":
        return "BLOCKED", "; ".join(r["reasons"])
    return "READY", "risk PASS"


def approved(o, now, log=None):
    """The latest yes for exactly this order, if it is recent enough."""
    log = log or load_log()
    key = rules.order_key(o)
    for e in reversed(log.get("log", [])):
        if e.get("key") == key and e.get("event") == "yes":
            at = datetime.datetime.strptime(e["at"], "%Y-%m-%d %H:%M:%S")
            return (now - at).total_seconds() <= APPROVAL_MINUTES * 60
    return False


def main(argv=None):
    p = cli.parser("Order tickets and your yes")
    p.add_argument("--now")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("show")
    c = sub.add_parser("confirm")
    c.add_argument("--index", type=int, required=True)
    c.add_argument("--reply", required=True, help='your reply, word for word; only "yes" approves')
    r = sub.add_parser("result")
    r.add_argument("--index", type=int, required=True)
    r.add_argument("--status", required=True, choices=["placed", "filled", "failed", "cancelled"])
    r.add_argument("--broker-id")
    r.add_argument("--filled-price", type=float)
    a = p.parse_args(argv)
    now = clock.parse_now(a.now)
    doc = config.read_json(cli.out_path("orders.json")) or {"orders": []}
    risk = config.read_json(cli.out_path("risk.json"))
    orders = doc["orders"]
    if a.cmd in ("confirm", "result") and not (1 <= a.index <= len(orders)):
        raise ValueError("no order %d in trader/orders.json" % a.index)
    if a.cmd == "show":
        if not orders:
            print("no orders: run prop-budget/size.py --write")
        for i, o in enumerate(orders, 1):
            st, why = status(o, i, risk, now)
            print("Ticket %d [%s] %s\n  %s" % (i, st, why, ticket_text(o)))
        return
    log = load_log()
    o = orders[a.index - 1]
    if a.cmd == "confirm":
        st, why = status(o, a.index, risk, now)
        if st != "READY":
            raise ValueError("ticket %d is %s (%s): it cannot be approved" % (a.index, st, why))
        ok = a.reply.strip().lower() == "yes"
        log["log"].append({"event": "yes" if ok else "no", "key": rules.order_key(o), "index": a.index,
                           "reply": a.reply, "at": now.strftime("%Y-%m-%d %H:%M:%S"),
                           "loss_at_stop_usd": o["loss_at_stop_usd"]})
        config.write_json(log_path(), log)
        print(("APPROVED for %d minutes: " % APPROVAL_MINUTES if ok else "NOT approved (only an exact yes counts): ")
              + ticket_text(o))
        return
    log["log"].append({"event": a.status, "key": rules.order_key(o), "index": a.index, "broker_id": a.broker_id,
                       "filled_price": a.filled_price, "at": now.strftime("%Y-%m-%d %H:%M:%S")})
    config.write_json(log_path(), log)
    print("recorded: ticket %d %s" % (a.index, a.status))


if __name__ == "__main__":
    cli.run(main)
