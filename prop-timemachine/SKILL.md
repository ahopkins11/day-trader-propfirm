---
name: prop-timemachine
description: >-
  Futures Time Machine for prop firm accounts. Before the user risks the account,
  replays the rest of the session thousands of times from the contract's own
  recent 5-minute bars and re-runs the same strategy on every past session, then
  gives the honest odds of target first, stop first or still open. Use when the
  user says "what are the odds", "replay it", "time machine", "backtest the ORB",
  "how has this setup done on ES".
---

# prop-timemachine

Not financial advice. The Time Machine is a simulation, not a prediction: it
is built from the last ~60 sessions, and the future can do what they never did
(a Fed day, a halt, a gap). It never places an order: that takes /prop-risk
and the user's own yes in /prop-broker.

## Run

```
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run                          # uses trader/plan.json
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --sims 10000 --seed 19 --offline trader/bars --write
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" history ES --offline trader/bars    # the strategy's record only
```

## How it works (say this plainly)

1. **Replays.** Each 5-minute bar after the entry is drawn from the same time
   of day on one of the past sessions (its move relative to the bar before),
   scaled to today's price. A bar that touches both the stop and the target
   counts as the stop. `--seed` makes a run repeatable.
2. **History.** The same strategy file runs on each past session; every signal
   is walked forward to the stop, the target or the flat-by time.
3. **Verdict.** Expected R per trade from the replays, plus the history's total.

## Tell the user

The three percentages, the history line (fired N times: X target, Y stop,
Z neither, total R), and the verdict. If the history fired fewer than 15
times, say the sample is small. Never round a coin flip up to an edge.

## Hard rules

- Never present the odds as a promise or a forecast.
- Yahoo keeps 60 days of 5-minute bars; for more, save ProjectX bars.
