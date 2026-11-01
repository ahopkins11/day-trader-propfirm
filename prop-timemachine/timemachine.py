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
    step = int(cfg.get("bar_minutes") or 5)
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
             "    target first %.1f %%   stop first %.1f %%   still open at the flat time %.1f %%" % (
                 mc["target_pct"], mc["stop_pct"], mc["flat_pct"]),
             "  The same strategy on the last %d sessions: fired %d times, %d hit the target, %d the stop, %d neither (%+.2fR)"
             % (h["sessions"], h["fired"], h["target"], h["stop"], h["flat"], h["total_r"]),
             "  Verdict: " + doc["verdict"],
             "  A simulation, not a prediction."]
    return "\n".join(lines)


def main(argv=None):
    ap = cli.parser("Replay a plan before you risk the account")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run")
    r.add_argument("--sims", type=int, default=10000)
    r.add_argument("--seed", type=int)
    r.add_argument("--offline")
    r.add_argument("--config")
    r.add_argument("--strategy")
    r.add_argument("--write", action="store_true")
    hi = sub.add_parser("history")
    hi.add_argument("symbol")
    hi.add_argument("--before", help="YYYY-MM-DD (default today)")
    hi.add_argument("--offline")
    hi.add_argument("--config")
    hi.add_argument("--strategy")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return
    cfg = config.load(a.config)
    strat, params = config.load_strategy(cfg, name=a.strategy)
    if a.cmd == "history":
        spec = contracts.spec(a.symbol)
        before = datetime.date.fromisoformat(a.before) if a.before else clock.parse_now(None).date()
        h = engine.history(strat, params, data.load(spec, offline=a.offline, days=60), spec, cfg, before)
        for t in h["trades"]:
            print("  %s  %s in at %-8s -> %-6s at %-14s %+.2fR" % (
                t["date"], t["side"], "%s %s" % (t["entry_at"], t["entry"]), t["outcome"],
                "%s %s" % (t["exit_at"] or "close", t["exit"]), t["r"]))
        print("%s on %d sessions: fired %d, target %d, stop %d, neither %d, total %+.2fR"
              % (strat.NAME, h["sessions"], h["fired"], h["target"], h["stop"], h["flat"], h["total_r"]))
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
