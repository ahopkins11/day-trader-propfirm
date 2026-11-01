# Strategies

**The trading rule lives here, and only here.** Every tool (scanner, entry
timer, exit planner, Time Machine) asks the active strategy file whether there
is a trade and where its entry, stop and target are. The contract math, sizing,
prop firm rules and order ticket don't care which strategy you use.

| file | what it is |
|------|------------|
| `orb.py` | **The ORB strategy** (opening range breakout), kept from upstream. The default. |
| `nyam.py` | **AJ's NYAM setup #1**: sweep into a 15m/1H FVG, 5m iFVG with displacement, nearest HTF DOL. |
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

## NYAM (strategies/nyam.py)

Mechanical version of Primary Setup #1 from the NYAM playbook. The rules and
every definition are written at the top of the file. Use
`config.nyam.example.json` as `trader/config.json`.

- **Bias:** `"bias": "auto"` (yesterday closed above the day before's high =
  long, below its low = short, else no trade) or set `"long"`, `"short"` or
  `"none"` each morning from your own Daily/4H/1H read.
- **Daily stop:** 1 loss, 2 breakevens or 2 wins (`DAILY_STOP` in the file,
  `personal.daily_stop` in the config for the live risk check).
- **Breakeven:** the plan gives a price; once it trades, move the stop to the
  entry by hand (TradingView and the bracket order won't do it for you).
- **What it can't see:** clean vs choppy, PD array and DOL quality, order and
  rejection blocks, OTE, the 10:00 4H-open setups and continuation trades.

```
python3 prop-timemachine/timemachine.py days MNQ --strategy nyam      # why each day did or didn't trade
python3 prop-timemachine/timemachine.py history MNQ --strategy nyam   # every trade and the total
python3 prop-timemachine/timemachine.py compare --strategy nyam       # MES, MNQ, MYM, M2K
```

Compare `days` with what you saw on those days: where the code and your eye
disagree is where a rule needs changing, or where your discretion is the edge.

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
