#!/usr/bin/env python3
"""Prop Exit Planner: the stop, the target and the flat time, in ticks and
dollars, before you enter.

  python3 prop-exit/exit.py plan --write                  # from trader/entry.json (the strategy's levels)
  python3 prop-exit/exit.py plan --symbol MES --side long --entry 6712.50 --stop 6705 --target-r 2 --write
  -> trader/plan.json

Prices are rounded to the contract's tick; a stop rounds away from the entry so
the risk is never understated. A stop is a plan, not a guarantee.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from propfirm import cli, clock, config, contracts, engine  # noqa: E402


def from_entry(entry_doc, cfg):
    if not entry_doc:
        raise ValueError("no trader/entry.json: run prop-entry check SYMBOL --write first, or pass --entry/--stop")
    if entry_doc.get("status") != "triggered" or not entry_doc.get("plan"):
        raise ValueError("trader/entry.json says %s (%s): nothing to plan yet"
                         % (entry_doc.get("status"), entry_doc.get("reason", "")))
    p = dict(entry_doc["plan"])
    p.update(symbol=entry_doc["symbol"], date=entry_doc["date"], strategy=entry_doc["strategy"],
             flat_by=entry_doc.get("flat_by") or cfg["flat_by"], source="strategy")
    return p


def manual(a, cfg, now):
    spec = contracts.spec(a.symbol)
    if a.target is None and a.target_r is None:
        raise ValueError("pass --target PRICE or --target-r 2")
    risk = abs(a.entry - a.stop)
    tgt = a.target if a.target is not None else (
        a.entry + a.target_r * risk if a.side == "long" else a.entry - a.target_r * risk)
    at = datetime.datetime.combine(now.date(), clock.parse_hhmm(a.at, "--at")) if a.at else now
    sess = clock.session(now.date(), spec)
    bar_index = None
    if sess:
        step = int(cfg.get("bar_minutes") or 5)
        bar_index = max(0, int((at - sess[0]).total_seconds() // (step * 60)) - 1)
    sig = {"side": a.side, "entry": a.entry, "stop": a.stop, "target": tgt, "why": "manual levels"}
    p = engine.finalize(sig, spec, cfg)
    p.update(symbol=spec["symbol"], date=now.date().isoformat(), strategy="manual", flat_by=cfg["flat_by"],
             source="manual", bar_index=bar_index, bar_close=at.strftime("%Y-%m-%d %H:%M"))
    return p


def describe(p):
    s = contracts.spec(p["symbol"])
    f = lambda x: contracts.fmt_price(x, s)  # noqa: E731
    return "\n".join([
        "%s %s  plan (%s)" % (p["symbol"], p["side"].upper(), p["strategy"]),
        "  entry  %s" % f(p["entry"]),
        "  stop   %s  (%d ticks, %.2f points, $%.2f per contract)" % (f(p["stop"]), p["risk_ticks"], p["risk_points"], p["risk_usd_per_contract"]),
        "  target %s  (%d ticks, $%.2f per contract, %.2fR)" % (f(p["target"]), p["reward_ticks"], p["reward_usd_per_contract"], p["reward_risk"] or 0),
        ("  breakeven: move the stop to %s once price touches %s" % (f(p["entry"]), f(p["breakeven"])))
        if p.get("breakeven") is not None else "  breakeven: none set by this strategy",
        "  flat by %s ET either way" % p["flat_by"],
        "  %s is $%.2f a point; a stop is a plan, not a guarantee (gaps and fast markets fill past it)." % (s["symbol"], s["point_value"]),
    ])


def main(argv=None):
    p = cli.parser("Plan the exit before the entry")
    sub = p.add_subparsers(dest="cmd")
    pl = sub.add_parser("plan")
    pl.add_argument("--symbol")
    pl.add_argument("--side", choices=["long", "short"], default="long")
    pl.add_argument("--entry", type=float)
    pl.add_argument("--stop", type=float)
    pl.add_argument("--target", type=float)
    pl.add_argument("--target-r", type=float)
    pl.add_argument("--at", help="entry time HH:MM ET for a manual plan (default now)")
    pl.add_argument("--now")
    pl.add_argument("--config")
    pl.add_argument("--write", action="store_true")
    a = p.parse_args(argv)
    if a.cmd != "plan":
        p.print_help()
        return
    cfg = config.load(a.config)
    now = clock.parse_now(a.now)
    if a.entry is not None or a.stop is not None:
        if None in (a.symbol, a.entry, a.stop):
            raise ValueError("a manual plan needs --symbol, --entry and --stop")
        plan = manual(a, cfg, now)
    else:
        plan = from_entry(config.read_json(cli.out_path("entry.json")), cfg)
    print(describe(plan))
    if a.write:
        config.write_json(cli.out_path("plan.json"), plan)
        print("wrote trader/plan.json")


if __name__ == "__main__":
    cli.run(main)
