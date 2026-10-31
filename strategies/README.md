# Strategies

**The trading rule lives here, and only here.** Every tool (scanner, entry
timer, exit planner, Time Machine) asks the active strategy file whether there
is a trade and where its entry, stop and target are. The contract math, sizing,
prop firm rules and order ticket don't care which strategy you use.

| file | what it is |
|------|------------|
| `orb.py` | **The ORB strategy** (opening range breakout), kept from upstream. The default. |
| `template.py` | A blank strategy to copy when you write your own. |

The active one is set in `trader/config.json`:

```json
"strategy": "orb",
"strategy_params": {"range_minutes": 15, "direction": "long", "stop": "mid", "target_r": 1.0}
```

## Tweak ORB without touching code

Change `strategy_params` in your config:

- `range_minutes`: 5, 15, 30 ... (a multiple of the 5-minute bar)
- `direction`: `"long"`, `"short"` or `"both"`
- `stop`: `"mid"` (range midpoint) or `"range"` (the far side of the range)
- `target_r`: 1.0 = 1R, 2.0 = 2R
- `min_volume_x`: e.g. 1.5 = the breakout bar needs 1.5x the range's average volume

## Add your own strategy

1. `cp strategies/template.py strategies/my_setup.py`
2. Set `NAME = "my_setup"`, write the rule in `evaluate()` (the docstring in
   `orb.py` lists everything `bars`, `p` and `ctx` contain and what to return).
3. In `trader/config.json`: `"strategy": "my_setup"`.
4. Check it on history before anything else:
   `python3 prop-timemachine/timemachine.py history MES --offline trader/bars`
5. Add a test next to `tests/test_core.py`'s `OrbKnownDay` with a day you
   know the answer for.

A strategy can also live in your project at `trader/strategies/my_setup.py`.
That copy wins over one with the same name here, so you can keep your own rule
private and out of the repo.

You can switch for a single command with `--strategy my_setup`
(scanner, entry, Time Machine), which is handy for comparing your rule with ORB
on the same history.

## Why not a third fork?

The strategy is the only part that differs between your setup and ORB, and
it's one file. A third fork would copy everything else (contracts, Topstep
rules, sizing, broker), so every fix would have to be made twice. Keeping
strategies as swappable files in this fork means one codebase, and you can
replay both rules on the same days and compare them.
