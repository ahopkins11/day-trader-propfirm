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

## NYAM indicator (nyam_indicator.pine)

The NYAM rules as a heads-up: it marks PDH/PDL, previous NYAM, Asia and London,
draws 15m/1H FVGs, and fires two alerts:

1. **SWEEP**: liquidity taken (from 5:00 AM) while price touched a 15m/1H FVG
   in the bias direction within 30 minutes. *Setup forming: drop to 30s.*
2. **5m iFVG**: a 5m candle closes through the last opposite 5m FVG with a body
   at least 1.3x the recent average, 9:30-11:00. Shows the stop (2 ticks beyond
   the sweep) and the nearest level ahead, with its distance in R from the 5m close.

You pick the precise entry on the 30-second chart. Add it the same way as the
ORB indicator; it works on 30s, 1m and 5m charts. Set Bias to long/short/none
in its settings if you read the bias yourself each morning.

Logging: record your actual entry, stop and result with
`python3 prop-risk/check.py account trade --pnl <dollars>` so your 30s entries
can be compared with the 5m backtest later.

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
