"""
=============================================================================
  STRATEGY TEMPLATE: copy me to strategies/<your_name>.py
=============================================================================

  1. Copy this file:   cp strategies/template.py strategies/my_setup.py
  2. Set NAME below to "my_setup" and describe the rule in plain words.
  3. Put your rule's knobs in PARAMS.
  4. Write evaluate(): look at today's closed bars and say whether there is a
     trade and where the entry, stop and target are.
  5. In trader/config.json set  "strategy": "my_setup"
  6. Run the tests:  python3 -m unittest discover -s tests
     and replay a past day:  python3 prop-entry/entry.py check ES --now "2026-10-19 10:30" --offline <bars>

  Everything else (contract math, sizing, Topstep rules, the Time Machine,
  the order ticket) works the same for any strategy that follows this shape.
  See strategies/orb.py for a complete working example.
=============================================================================
"""

NAME = "template"
DESCRIPTION = "Describe your rule in one line"

PARAMS = {
    # "example_knob": 10,
    "target_r": 2.0,
}


def evaluate(bars, p, ctx):
    """See strategies/orb.py for what bars, p and ctx contain and what to return."""
    if len(bars) < 3:
        return {"status": "forming", "signal": None, "levels": {}, "reason": "waiting for 3 bars"}

    for b in bars:
        if not ctx["can_enter"](b):
            continue
        # ---- your entry rule goes here --------------------------------
        # Example (replace it): a bar that closes above the previous bar's high.
        prev = [x for x in bars if x["i"] == b["i"] - 1]
        if prev and b["c"] > prev[0]["h"]:
            entry = b["c"]
            stop = b["l"]                                # your stop rule
            target = entry + p["target_r"] * (entry - stop)  # your target rule
            return {"status": "triggered", "levels": {}, "reason": "example rule fired",
                    "signal": {"side": "long", "entry": entry, "stop": stop, "target": target,
                               "bar": b, "why": "close above previous high"}}
        # ----------------------------------------------------------------

    return {"status": "waiting", "signal": None, "levels": {}, "reason": "no setup yet"}
