# Paper trading on TradingView

TradingView doesn't run the Python tools and can't take orders from them. Here's how the two fit together:

| piece | where it runs | what it does |
|-------|---------------|--------------|
| `orb_indicator.pine` | TradingView | Draws the ORB range, the signal, the stop and the target, and fires an alert. |
| the `prop-*` skills | your Mac (Claude Code) | Confirms the signal, replays the odds, sizes contracts, checks the Topstep rules. |
| you | TradingView Paper Trading | Places the order, the stop and the target by hand. |

## Add the indicator

1. Open a **5-minute** chart of `MES1!` or `MNQ1!` (or `ES1!` / `NQ1!`).
2. Open the **Pine Editor** at the bottom of the chart, create a new indicator,
   delete what's there, and paste in all of `orb_indicator.pine`.
3. Click **Save**, then **Add to chart**.
4. Its settings (gear icon) match `strategy_params` and the entry window in
   `trader/config.json`. Keep the two the same, or the chart and the tools
   will disagree.

**Alert:** Alerts > Create > Condition: "ORB - day-trader-propfirm" >
"Any alert() function call". It fires once when the breakout bar closes, and
again at the flat time if a trade is still open.

## One paper trade

1. The alert fires, or `/prop-entry check MES` says TRIGGERED.
2. `/prop-exit plan --write`, `/prop-timemachine run`, `/prop-budget --write`, `/prop-risk check`.
3. If it's PASS, place it in TradingView's Paper Trading panel: market order,
   the contracts `prop-budget` gave, and stop loss and take profit at the
   plan's prices (Paper Trading lets you attach both to the order).
4. When it closes: `python3 prop-risk/check.py account trade --pnl <dollars>`.
   After the session: `python3 prop-risk/check.py account eod --balance <paper balance>`.

## Symbols

| TradingView | the tools |
|-------------|-----------|
| `MES1!` | `MES` |
| `MNQ1!` | `MNQ` |
| `ES1!` | `ES` |
| `NQ1!` | `NQ` |

The tools read Yahoo's prices, which can be a tick or two off TradingView's
or a little delayed. When they disagree, trust TradingView's chart.

## Use TradingView's own bars in the tools (optional)

On plans that allow chart data export (chart menu > Export chart data), save a
5-minute `MES1!` export as `trader/bars/MES.csv` (ISO or UNIX times) and run
any tool with `--offline trader/bars`. For example:

```
python3 prop-timemachine/timemachine.py history MES --offline trader/bars
```

Not financial advice.
