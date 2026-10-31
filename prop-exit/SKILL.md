---
name: prop-exit
description: >-
  Futures Exit Planner for prop firm accounts. Turns the strategy's signal (or
  levels the user gives) into a tick-exact plan: entry, stop, target, ticks,
  points, dollars per contract, reward to risk and the flat-by time, written to
  trader/plan.json before the entry. Use when the user says "plan the exit",
  "where's my stop", "set my target", "how many ticks", "what's 1R on ES".
---

# prop-exit

Not financial advice. A stop is a plan, not a guarantee: in a fast market or
across a gap a stop can fill past its price. Planning an exit never places an
order; orders need /prop-risk and the user's yes in /prop-broker.

## Run

```
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --write                  # from trader/entry.json
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --symbol MES --side long --entry 6712.50 --stop 6705 --target-r 2 --write
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --symbol NQ --side short --entry 21050 --stop 21075 --target 21000 --at 10:05 --write
```

- Prices are rounded to the contract's tick. The stop rounds AWAY from the
  entry so the risk shown is never smaller than the real one.
- The stop and target rules come from the strategy file (ORB: range midpoint,
  1R). A manual plan overrides them for this trade only.
- `flat_by` comes from the config (15:55 ET by default). Topstep has its own
  end-of-day cutoff for open positions: check it in your plan's rules.

## Contract math to say out loud

ES and MES move in 0.25 ticks: ES $12.50 a tick ($50 a point), MES $1.25 ($5).
NQ $5 a tick ($20 a point), MNQ $0.50 ($2). See `propfirm/contracts.py`.

## Hard rules

- Never plan a trade without a stop.
- Never say the target is likely; the Time Machine gives the odds.
