#!/usr/bin/env python3
"""Prop Time Machine: before you risk the account, replay the rest of the
session thousands of times, and re-run the same strategy on every past session.

  python3 prop-timemachine/timemachine.py run                    # uses trader/plan.json
  python3 prop-timemachine/timemachine.py run --sims 10000 --seed 19 --offline trader/bars --write
  python3 prop-timemachine/timemachine.py history ES --offline trader/bars   # the strategy's record only

How the replay works: each 5-minute bar after your entry is drawn from the same
time of day on one of the last ~59 sessions (its move relative to the bar
before it), scaled to today's price. A bar that touches both the stop and the
target counts as the stop. The odds are a reality check, never a promise: the
future can do what those sessions never did (a Fed day, a halt, a gap).
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from propfirm import cli, clock, config, contracts, data, engine  # noqa: E402


def replay(plan, bars, cfg, strat, params, sims=10000, seed=None, n_hist=59):
    spec = contracts.spec(plan["symbol"])
    day = datetime.date.fromisoformat(plan["date"])
    step = int(plan.get("bar_minutes") or cfg.get("bar_minutes") or 5)
    cfg = dict(cfg, bar_minutes=step)          # replay with the candle size the plan was made on
    sess = clock.session(day, spec)
    if not sess:
        raise ValueError("no regular session on %s" % day)
    _, _, flat = engine.entry_window(day, sess, cfg)
    past = data.past_sessions(bars, day, spec, n=n_hist, bar_minutes=step)
    if len(past) < 10:
        raise ValueError("only %d past sessions in the data: the replay wants 10 or more (load 60 days)" % len(past))
    start = (plan.get("bar_index") or 0) + 1
    end = int((flat - sess[0]).total_seconds() // (step * 60))
    mc = engine.simulate(plan, start, end, engine.slot_pools(past, step), sims=sims, seed=seed)
    hist = engine.history(strat, params, bars, spec, cfg, day, n=n_hist)
    return {"symbol": spec["symbol"], "date": plan["date"], "strategy": strat.NAME, "plan": plan,
            "flat_by": clock.hm(flat), "monte_carlo": mc, "history": hist, "verdict": verdict(mc, hist)}


def verdict(mc, hist):
    t, s = mc["target_pct"], mc["stop_pct"]
    if mc["expected_r"] > 0.15 and t > s:
        v = "the replay leans your way (expected %+.2fR per trade)" % mc["expected_r"]
    elif mc["expected_r"] < -0.15:
        v = "the replay leans against you (expected %+.2fR per trade)" % mc["expected_r"]
    else:
        v = "close to a coin flip (expected %+.2fR per trade)" % mc["expected_r"]
    if hist["fired"]:
        v += "; on the last %d sessions the rule fired %d times for %+.2fR in total" % (
            hist["sessions"], hist["fired"], hist["total_r"])
    if hist["fired"] < 15:
        v += " (a small sample)"
    return v


def describe(doc):
    mc, h = doc["monte_carlo"], doc["history"]
    p = doc["plan"]
    lines = ["Time Machine: %s %s %s, %s" % (doc["symbol"], p["side"].upper(), p["entry"], doc["date"]),
             "  %d replays of the rest of the day (seed %s), flat by %s:" % (mc["sims"], mc["seed"], doc["flat_by"]),
             "    target first %.1f %%   stop first %.1f %%%s   still open at the flat time %.1f %%" % (
                 mc["target_pct"], mc["stop_pct"],
                 ("   breakeven %.1f %%" % mc["breakeven_pct"]) if "breakeven_pct" in mc else "", mc["flat_pct"]),
             "  The same strategy on the last %d sessions: fired %d times, %d hit the target, %d the stop, %d breakeven, %d neither (%+.2fR)"
             % (h["sessions"], h["fired"], h["target"], h["stop"], h.get("breakeven", 0), h["flat"], h["total_r"]),
             "  Verdict: " + doc["verdict"],
             "  A simulation, not a prediction."]
    return "\n".join(lines)


VARIANTS = [  # (label, candle minutes, last entry time)
    ("5m candles, entries until 3 PM", 5, "15:00"),
    ("15m candles, entries until 3 PM", 15, "15:00"),
    ("15m candles, entries until 11 AM", 15, "11:00"),
]


def max_drawdown(rs):
    bal = peak = dd = 0.0
    for r in rs:
        bal += r
        peak = max(peak, bal)
        dd = max(dd, peak - bal)
    return dd


def compare(symbols, cfg, strat, params, before, loader, variants=None):
    """Run each variant on each symbol over the same days. Returns rows and per-variant totals."""
    rows, totals = [], []
    bars_by = {}
    for sym in symbols:
        spec = contracts.spec(sym)
        try:
            bars_by[sym] = (spec, loader(spec))
        except data.DataError as e:
            rows.append({"symbol": spec["symbol"], "variant": "-", "error": str(e)})
    if variants is None:
        if strat.NAME == "orb":
            variants = VARIANTS
        else:   # any other strategy: one row per market, as its file and the config define it
            variants = [("%s as configured" % strat.NAME, cfg.get("bar_minutes") or 5, cfg["no_entries_after"])]
    for label, bm, last in variants:
        vcfg = dict(cfg, bar_minutes=bm, no_entries_after=last)
        all_trades = []
        for sym, (spec, bars) in bars_by.items():
            h = engine.history(strat, params, bars, spec, vcfg, before)
            usd = sum(t["r"] * contracts.dollars(contracts.ticks_between(t["entry"], t["stop"], spec), spec)
                      for t in h["trades"])
            rows.append({"symbol": spec["symbol"], "variant": label, "sessions": h["sessions"], "trades": h["fired"],
                         "wins": h["target"], "losses": h["stop"], "be": h.get("breakeven", 0), "flat": h["flat"],
                         "total_r": h["total_r"],
                         "max_dd_r": round(max_drawdown([t["r"] for t in h["trades"]]), 2),
                         "usd_1_contract": round(usd, 2)})
            all_trades += [dict(t, symbol=spec["symbol"]) for t in h["trades"]]
        all_trades.sort(key=lambda t: (t["date"], t["entry_at"]))
        n = len(all_trades)
        wins = sum(1 for t in all_trades if t["outcome"] == "target")
        tot = round(sum(t["r"] for t in all_trades), 2)
        totals.append({"variant": label, "trades": n, "wins": wins, "win_pct": round(100.0 * wins / n, 1) if n else 0,
                       "total_r": tot, "avg_r": round(tot / n, 3) if n else 0,
                       "max_dd_r": round(max_drawdown([t["r"] for t in all_trades]), 2),
                       "positive_markets": sum(1 for r in rows if r.get("variant") == label and r["total_r"] > 0),
                       "markets": len(bars_by)})
    return rows, totals


def show_compare(rows, totals, strat):
    print("%s: each version on each market, same days\n" % strat.NAME)
    print("  %-5s %-34s %6s %5s %5s %5s %5s %8s %7s %10s" % ("mkt", "version", "trades", "win", "loss", "BE", "flat", "total R", "max DD", "$ 1 contr"))
    for r in rows:
        if "error" in r:
            print("  %-5s %s" % (r["symbol"], r["error"]))
            continue
        print("  %-5s %-34s %6d %5d %5d %5d %5d %+8.2f %7.2f %10.2f" % (r["symbol"], r["variant"], r["trades"], r["wins"],
              r["losses"], r["be"], r["flat"], r["total_r"], r["max_dd_r"], r["usd_1_contract"]))
    print("\nAll markets together:")
    print("  %-34s %6s %6s %8s %7s %7s %9s" % ("version", "trades", "win %", "total R", "avg R", "max DD", "markets +"))
    for t in totals:
        print("  %-34s %6d %6.1f %+8.2f %+7.3f %7.2f %6d of %d" % (t["variant"], t["trades"], t["win_pct"], t["total_r"],
              t["avg_r"], t["max_dd_r"], t["positive_markets"], t["markets"]))
    print("\nR is comparable across markets; dollars are for 1 contract of each (MNQ moves more per point than MES).")
    print("Before fees. Max DD is the worst drop from a high, in R. A backtest, not a promise.")


def main(argv=None):
    ap = cli.parser("Replay a plan before you risk the account")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run")
    r.add_argument("--sims", type=int, default=10000)
    r.add_argument("--seed", type=int)
    r.add_argument("--offline")
    r.add_argument("--config")
    r.add_argument("--strategy")
    r.add_argument("--param", action="append", metavar="KEY=VALUE", help="override a strategy setting for this run")
    r.add_argument("--bar-minutes", type=int)
    r.add_argument("--write", action="store_true")
    hi = sub.add_parser("history")
    hi.add_argument("symbol")
    hi.add_argument("--before", help="YYYY-MM-DD (default today)")
    hi.add_argument("--offline")
    hi.add_argument("--config")
    hi.add_argument("--strategy")
    hi.add_argument("--param", action="append", metavar="KEY=VALUE", help="override a strategy setting for this run")
    hi.add_argument("--bar-minutes", type=int)
    dy = sub.add_parser("days", help="why the strategy did or didn't trade, day by day")
    dy.add_argument("symbol")
    dy.add_argument("--before", help="YYYY-MM-DD (default today)")
    dy.add_argument("--offline")
    dy.add_argument("--config")
    dy.add_argument("--strategy")
    dy.add_argument("--param", action="append", metavar="KEY=VALUE", help="override a strategy setting for this run")
    dy.add_argument("--bar-minutes", type=int)
    cp = sub.add_parser("compare", help="all three ORB versions on several markets")
    cp.add_argument("--symbols", default="MES,MNQ,MYM,M2K")
    cp.add_argument("--before", help="YYYY-MM-DD (default today)")
    cp.add_argument("--offline")
    cp.add_argument("--config")
    cp.add_argument("--strategy")
    cp.add_argument("--param", action="append", metavar="KEY=VALUE", help="override a strategy setting for this run")
    cp.add_argument("--write", action="store_true", help="save to trader/compare.json")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return
    cfg = cli.apply_bar_minutes(config.load(a.config), a)
    strat, params = config.load_strategy(cfg, name=a.strategy)
    params = cli.apply_params(params, a)
    if a.cmd == "days":
        spec = contracts.spec(a.symbol)
        before = datetime.date.fromisoformat(a.before) if a.before else clock.parse_now(None).date()
        bars = data.load(spec, offline=a.offline, days=60)
        for day, _ in data.past_sessions(bars, before, spec, bar_minutes=engine.bar_minutes(strat, cfg)):
            res = engine.evaluate_day(strat, params, bars, clock.session(day, spec)[1], spec, cfg)
            why = res["reason"]
            if res["status"] == "expired" and "(" in why:
                why = why[why.index("(") + 1:-1]       # the strategy's own reason inside "no signal by ..."
            if res["status"] == "triggered":
                pl = res["plan"]
                why = "TRADE %s %s at %s, stop %s, target %s: %s" % (pl["side"], pl["entry"], pl["bar_close"][11:],
                                                                   pl["stop"], pl["target"], res["reason"])
            print("  %s %s  %s" % (day.isoformat(), day.strftime("%a"), why))
        return
    if a.cmd == "compare":
        before = datetime.date.fromisoformat(a.before) if a.before else clock.parse_now(None).date()
        syms = [s.strip() for s in a.symbols.split(",") if s.strip()]
        rows, totals = compare(syms, cfg, strat, params, before,
                               lambda s: data.load(s, offline=a.offline, days=60))
        show_compare(rows, totals, strat)
        if a.write:
            config.write_json(cli.out_path("compare.json"), {"rows": rows, "totals": totals})
            print("wrote trader/compare.json")
        return
    if a.cmd == "history":
        spec = contracts.spec(a.symbol)
        before = datetime.date.fromisoformat(a.before) if a.before else clock.parse_now(None).date()
        h = engine.history(strat, params, data.load(spec, offline=a.offline, days=60), spec, cfg, before)
        for t in h["trades"]:
            print("  %s  %s in at %-8s -> %-6s at %-14s %+.2fR" % (
                t["date"], t["side"], "%s %s" % (t["entry_at"], t["entry"]), t["outcome"],
                "%s %s" % (t["exit_at"] or "close", t["exit"]), t["r"]))
        print("%s, %d-minute bars, on %d sessions: fired %d, target %d, stop %d, breakeven %d, neither %d, total %+.2fR"
              % (strat.NAME, engine.bar_minutes(strat, cfg), h["sessions"], h["fired"], h["target"], h["stop"],
                 h.get("breakeven", 0), h["flat"], h["total_r"]))
        return
    plan = config.read_json(cli.out_path("plan.json"))
    if not plan:
        raise ValueError("no trader/plan.json: run prop-exit plan --write first")
    bars = data.load(contracts.spec(plan["symbol"]), offline=a.offline, days=60)
    doc = replay(plan, bars, cfg, strat, params, sims=a.sims, seed=a.seed)
    print(describe(doc))
    if a.write:
        config.write_json(cli.out_path("timemachine.json"), doc)
        print("wrote trader/timemachine.json")


if __name__ == "__main__":
    cli.run(main)
