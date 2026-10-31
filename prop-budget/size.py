#!/usr/bin/env python3
"""Prop Position Sizer: how many contracts the plan allows, in whole contracts.

  python3 prop-budget/size.py               # from trader/plan.json
  python3 prop-budget/size.py --write       # -> trader/orders.json (one bracket order)

contracts = the smallest of
  your max loss per trade          / risk per contract
  what is left of today's limits   / risk per contract   (yours and the firm's, minus your buffer)
  room above the trailing max loss / risk per contract
  the plan's and your max contracts (10 micros count as 1 full-size)
If not even 1 full-size contract fits, it sizes the micro (ES -> MES) instead.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from propfirm import cli, clock, config, contracts, rules  # noqa: E402


def size(plan, cfg, st):
    spec = contracts.spec(plan["symbol"])
    out = _size(plan, spec, cfg, st)
    if out["contracts"] == 0 and spec.get("micro"):
        mspec = contracts.spec(spec["micro"])
        mplan = dict(plan)
        fees = float(cfg.get("fees_per_contract_round_trip") or 0)
        mplan["risk_usd_per_contract"] = round(contracts.dollars(plan["risk_ticks"], mspec) + fees, 2)
        mplan["reward_usd_per_contract"] = round(contracts.dollars(plan["reward_ticks"], mspec) - fees, 2)
        m = _size(mplan, mspec, cfg, st)
        if m["contracts"] > 0:
            m["note"] = "not even 1 %s fits your limits, so this is sized in %s (same prices, a tenth the size)" % (
                spec["symbol"], mspec["symbol"])
            return m
    return out


def _size(plan, spec, cfg, st):
    me, acct = cfg["personal"], cfg["account"]
    per = float(plan["risk_usd_per_contract"])
    rm = rules.room(cfg, st)
    budget = min([float(me["max_loss_per_trade_usd"])] + list(rm.values()))
    by_risk = int(math.floor(max(budget, 0) / per)) if per > 0 else 0
    ratio = 1 if not spec.get("is_micro") else int(acct.get("micros_per_contract") or 10)
    cap = int(math.floor(min(float(acct["max_contracts"]), float(me.get("max_contracts") or acct["max_contracts"])) * ratio))
    n = max(0, min(by_risk, cap))
    limit = "risk" if by_risk <= cap else "max contracts"
    return {"symbol": spec["symbol"], "side": plan["side"], "contracts": n,
            "type": "market", "entry": plan["entry"], "stop": plan["stop"], "target": plan["target"],
            "stop_ticks": plan["risk_ticks"], "target_ticks": plan["reward_ticks"],
            "loss_at_stop_usd": round(per * n, 2),
            "gain_at_target_usd": round(float(plan["reward_usd_per_contract"]) * n, 2),
            "reward_risk": plan["reward_risk"], "date": plan["date"], "flat_by": plan["flat_by"],
            "strategy": plan.get("strategy"), "limited_by": limit, "budget_usd": round(budget, 2)}


def main(argv=None):
    p = cli.parser("Size the plan in contracts")
    p.add_argument("--config")
    p.add_argument("--now")
    p.add_argument("--write", action="store_true")
    a = p.parse_args(argv)
    cfg = config.load(a.config)
    plan = config.read_json(cli.out_path("plan.json"))
    if not plan:
        raise ValueError("no trader/plan.json: run prop-exit plan --write first")
    st = rules.load_state(cfg, clock.parse_now(a.now).date())
    o = size(plan, cfg, st)
    s = contracts.spec(o["symbol"])
    print("%s %d %s at %s, stop %s (%d ticks), target %s (%d ticks)" % (
        "BUY" if o["side"] == "long" else "SELL", o["contracts"], o["symbol"], contracts.fmt_price(o["entry"], s),
        contracts.fmt_price(o["stop"], s), o["stop_ticks"], contracts.fmt_price(o["target"], s), o["target_ticks"]))
    print("  loss at the stop $%.2f, gain at the target $%.2f; limited by %s (budget $%.2f)"
          % (o["loss_at_stop_usd"], o["gain_at_target_usd"], o["limited_by"], o["budget_usd"]))
    if o.get("note"):
        print("  " + o["note"])
    if o["contracts"] == 0:
        print("  0 contracts: the stop is too wide for your limits today. Skip it or tighten the plan.")
    if a.write:
        config.write_json(cli.out_path("orders.json"), {"orders": [o]})
        print("wrote trader/orders.json")


if __name__ == "__main__":
    cli.run(main)
