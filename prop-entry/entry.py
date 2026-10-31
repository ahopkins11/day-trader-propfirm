#!/usr/bin/env python3
"""Prop Entry Timer: is the setup forming, waiting, triggered or expired?

  python3 prop-entry/entry.py check MES                       # right now
  python3 prop-entry/entry.py check ES --now "2026-10-19 10:30" --offline trader/bars
  python3 prop-entry/entry.py watch MNQ --every 30            # bar by bar until it triggers
  --write saves the verdict to trader/entry.json for prop-exit.

Yahoo's futures bars can lag. Before entering, check the price on your platform.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from propfirm import cli, clock, config, contracts, data, engine  # noqa: E402

FINAL = ("triggered", "expired", "closed")


def describe(res):
    lines = ["%s  %s  [%s]  %s" % (res["symbol"], res["status"].upper(), res["strategy"], res.get("reason", ""))]
    lv = res.get("levels") or {}
    if "range_high" in lv:
        lines.append("  opening range %.2f to %.2f (mid %.2f)" % (lv["range_low"], lv["range_high"], lv["range_mid"]))
    if res.get("last"):
        lines.append("  last closed bar %s at %.2f" % (res["last"]["bar_start"], res["last"]["close"]))
    p = res.get("plan")
    if p:
        s = contracts.spec(res["symbol"])
        lines.append("  %s at %s (bar closed %s)  stop %s  target %s" % (
            p["side"].upper(), contracts.fmt_price(p["entry"], s), p["bar_close"][11:],
            contracts.fmt_price(p["stop"], s), contracts.fmt_price(p["target"], s)))
        lines.append("  risk %d ticks = $%.2f per contract, reward %d ticks, %.2fR" % (
            p["risk_ticks"], p["risk_usd_per_contract"], p["reward_ticks"], p["reward_risk"] or 0))
    if res.get("no_entries_after"):
        lines.append("  entries %s-%s ET, flat by %s" % (res["no_entries_before"], res["no_entries_after"], res["flat_by"]))
    return "\n".join(lines)


def check(sym, cfg, strat, params, now, offline=None, loader=None):
    spec = contracts.spec(sym)
    bars = (loader or (lambda s: data.load(s, offline=offline, days=5)))(spec)
    return engine.evaluate_day(strat, params, bars, now, spec, cfg)


def main(argv=None):
    p = cli.parser("Entry timer for the active strategy")
    sub = p.add_subparsers(dest="cmd")
    c = cli.common(sub.add_parser("check"), symbol=True)
    w = cli.common(sub.add_parser("watch"), symbol=True)
    w.add_argument("--every", type=int, default=30, help="seconds between checks")
    w.add_argument("--max-checks", type=int, default=2000)
    a = p.parse_args(argv)
    if not a.cmd:
        p.print_help()
        return
    cfg, strat, params, _ = cli.setup(a)
    if a.cmd == "check":
        res = check(a.symbol, cfg, strat, params, clock.parse_now(a.now), offline=a.offline)
        print(describe(res))
    else:
        res = None
        for _ in range(a.max_checks):
            res = check(a.symbol, cfg, strat, params, clock.parse_now(a.now), offline=a.offline)
            print("[%s] %s %s" % (res["now"][11:], res["status"].upper(), res.get("reason", "")))
            if res["status"] in FINAL or a.now:
                break
            time.sleep(max(5, a.every))
        print(describe(res))
    if a.write:
        config.write_json(cli.out_path("entry.json"), res)
        print("wrote trader/entry.json")


if __name__ == "__main__":
    cli.run(main)
