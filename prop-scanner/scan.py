#!/usr/bin/env python3
"""Prop Scanner: run the active strategy on every contract in your watchlist.

  python3 prop-scanner/scan.py                         # config symbols, now
  python3 prop-scanner/scan.py --symbols ES,NQ,MES,MNQ --now "2026-10-19 10:30"
  python3 prop-scanner/scan.py --offline trader/bars --write   # -> trader/scan.json

A scan lists contracts where the rule fired, not trades to take.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from propfirm import cli, config, contracts, data, engine  # noqa: E402


def scan(symbols, cfg, strat, params, now, offline=None, loader=None):
    loader = loader or (lambda s: data.load(s, offline=offline, days=5))
    rows = []
    for sym in symbols:
        try:
            spec = contracts.spec(sym)
            res = engine.evaluate_day(strat, params, loader(spec), now, spec, cfg)
        except (contracts.ContractError, data.DataError, engine.EngineError) as e:
            res = {"symbol": sym.upper(), "status": "error", "reason": str(e)}
        rows.append(res)
    return {"now": now.strftime("%Y-%m-%d %H:%M"), "strategy": strat.NAME, "results": rows,
            "note": "A scan is a list of contracts where the rule fired, not a list of trades to take."}


def show(doc):
    print("Strategy: %s   at %s ET" % (doc["strategy"], doc["now"]))
    for r in doc["results"]:
        line = "  %-4s %-10s %s" % (r["symbol"], r["status"].upper(), r.get("reason", ""))
        p = r.get("plan")
        if p:
            spec = contracts.spec(r["symbol"])
            line += "\n       %s %s  stop %s  target %s  (%d ticks risk = $%.2f per contract, %.2fR)" % (
                p["side"].upper(), contracts.fmt_price(p["entry"], spec), contracts.fmt_price(p["stop"], spec),
                contracts.fmt_price(p["target"], spec), p["risk_ticks"], p["risk_usd_per_contract"], p["reward_risk"] or 0)
        print(line)
    print(doc["note"])


def main(argv=None):
    p = cli.common(cli.parser("Run the strategy across your watchlist"), symbols=True)
    a = p.parse_args(argv)
    cfg, strat, params, now = cli.setup(a)
    syms = [s.strip() for s in (a.symbols.split(",") if a.symbols else cfg["symbols"]) if s.strip()]
    doc = scan(syms, cfg, strat, params, now, offline=a.offline)
    show(doc)
    if a.write:
        config.write_json(cli.out_path("scan.json"), doc)
        print("wrote trader/scan.json")


if __name__ == "__main__":
    cli.run(main)
