# The Day Trader skill: Prop Firm edition

Claude skills for day trading **futures on a prop firm account** (built for
Topstep): scan your contracts, time the entry, plan the exit in ticks, replay
the odds, size in contracts against the firm's drawdown rules, and send a
bracket order through TopstepX's API only after you say yes.

A fork of [Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
(MIT), which trades US stocks in your own brokerage account. For that, use
the sibling fork `day-trader-alpaca`.

## Where the strategy is

**`strategies/orb.py`**: that file is the whole trading rule, and nothing
else in the repo decides when to trade. It's the upstream opening range
breakout: the first 5-minute close outside the 9:30-9:45 range, stop at the
range midpoint, 1R target.

- **`strategies/nyam.py`** is AJ's NYAM sweep + iFVG setup. Switch with
  `config.nyam.example.json` or `--strategy nyam`.
- Tweak it from `trader/config.json` (`strategy_params`) without touching code.
- Swap in your own: copy `strategies/template.py`, write the rule, set
  `"strategy": "your_name"`. Full guide: [strategies/README.md](strategies/README.md).

## Paper trading on TradingView

Start here if you're practicing before a real Combine: copy
`config.tradingview.example.json` to `trader/config.json`, add
`tradingview/orb_indicator.pine` to a 5-minute MES1! or MNQ1! chart, and place
the trades by hand in TradingView Paper Trading. Guide:
[tradingview/README.md](tradingview/README.md).

## The skills

| command | job | what it does |
|---------|-----|--------------|
| `/prop-scanner` | Watchlist Scanner | Runs the strategy on every contract you watch (ES, NQ, micros ...). |
| `/prop-entry` | Entry Timer | Forming, waiting, triggered or expired, bar by bar. |
| `/prop-exit` | Exit Planner | Entry, stop, target in ticks, points and dollars per contract, before you enter. |
| `/prop-timemachine` | Time Machine | 10,000 replays of the rest of the session, plus the strategy on every past session. |
| `/prop-budget` | Position Sizer | Whole contracts from your limits and the firm's; drops to micros when ES/NQ don't fit. |
| `/prop-risk` | Risk Manager | PASS or BLOCK: trailing max loss, daily loss limit, max contracts, your limits, news windows. |
| `/prop-broker` | Order Ticket | Your yes, then a bracket order through the ProjectX API: dry run by default, your computer only. |

One trade:

```
scanner -> entry -> exit -> timemachine -> budget -> risk -> broker
after it closes:  prop-risk account trade --pnl ...    after the session:  prop-risk account eod
```

## Install

As a plugin in Claude Code:

```
/plugin marketplace add ahopkins11/day-trader-propfirm
/plugin install day-trader-propfirm@day-trader-propfirm
```

Or copy the folders (the skills need `propfirm/` and `strategies/` next to them):

```
git clone https://github.com/ahopkins11/day-trader-propfirm.git
cp -r day-trader-propfirm/prop-* day-trader-propfirm/propfirm day-trader-propfirm/strategies ~/.claude/skills/
```

You need Python 3.8 or newer, and there's nothing to pip install.

## Set up

1. `mkdir trader && cp config.example.json trader/config.json` in the project you trade from.
2. **Copy your plan's real numbers** from the Topstep dashboard into the
   `account` block: starting balance, max loss limit (and whether it trails end
   of day), daily loss limit, profit target, max contracts. The shipped numbers
   are an example 50K Combine; firms change their rules.
3. Set your own tighter limits in `personal`, and the stage (`combine`, `express`, `live`).
4. Tell the tools your balance: `python3 prop-risk/check.py account set --balance 50000`.
5. Add the week's scheduled news (CPI, FOMC, jobs) to `news_events`.
6. Optional, for API orders: subscribe to TopstepX API access, turn on Auto OCO
   Brackets, and set `PROJECTX_USERNAME` / `PROJECTX_API_KEY` in your terminal.
   Run the whole flow on a Practice account first.

## The tools

```
python3 prop-scanner/scan.py --symbols MES,MNQ
python3 prop-entry/entry.py check MES --write                 # -> trader/entry.json
python3 prop-entry/entry.py watch MNQ --every 30 --write
python3 prop-exit/exit.py plan --write                        # -> trader/plan.json
python3 prop-timemachine/timemachine.py run --seed 19 --write
python3 prop-timemachine/timemachine.py history MES           # the strategy's record, 59 sessions
python3 prop-budget/size.py --write                           # -> trader/orders.json
python3 prop-risk/check.py check                              # PASS / BLOCK -> trader/risk.json
python3 prop-risk/check.py account show
python3 prop-broker/ticket.py show
python3 prop-broker/ticket.py confirm --index 1 --reply "yes"
python3 prop-broker/projectx.py place --index 1 --account-id ID          # dry run
python3 prop-broker/projectx.py bars MES --days 60 --out trader/bars/MES.json
python3 -m unittest discover -s tests
```

Every tool takes `--now "2026-10-19 10:30"` (New York) to replay a moment,
and `--offline FILE_OR_FOLDER` to use saved bars instead of Yahoo.

## What changed from upstream

- **Futures, not stocks.** `propfirm/contracts.py` holds tick size, tick value,
  point value and session for ES, NQ, YM, RTY, CL, GC and their micros. Prices
  round to the tick, and stops round away from the entry.
- **Strategy in one file.** Upstream's ORB logic was spread across four tools.
  Here it's `strategies/orb.py`, and every tool calls it through one interface.
- **Prop firm rules.** Trailing max loss (end of day or intraday, optionally
  stopping at the starting balance), the firm's daily loss limit, contract
  limits with 10 micros = 1, your buffer, a news blackout, and the
  Live Funded warning.
- **ProjectX instead of Alpaca/IBKR.** TopstepX's API, with a dry run by
  default and a second typed yes in the terminal.
- **Dropped:** the stock-only skills (news on tickers, SEC earnings, Pelosi
  tracker, the 5,900-stock universe, price alerts).

## Fine print

**Not financial advice.** This is software that does arithmetic on public
data. It doesn't know your situation and it can't see the future. Most people
who day trade lose money, and most prop firm evaluations are not passed.

**Follow your firm's rules.** Topstep allows automated strategies and its
API, with conditions: no trading from a VPS, VPN or remote server (that
includes cloud sessions), no API trading on Live Funded accounts, no
high-frequency or simulator-exploiting strategies. Rule breaks count the same
whether you or a bot caused them. Read your plan's current rules yourself;
this repo can't keep up with them.

**No trade goes through until you say yes.** Only `prop-broker/projectx.py
place --send` can send an order. It needs a risk PASS for that exact order,
your recorded yes from the last 15 minutes, and a second typed yes. API
orders are final.

**The data is free and unofficial.** Yahoo's futures bars are the continuous
front month and can be delayed. Check prices on TopstepX before acting.
ProjectX bars (`projectx.py bars`) are the better source for replays.

**The Time Machine is a simulation, not a prediction.** A stop is a plan,
not a guarantee.

**The tests use synthetic bars.** `tests/fixtures/ES-synthetic-5m.json` is a
seeded random walk with one hand-built day (see `tests/make_fixtures.py`). It
checks the math, not the strategy's real edge. Run `timemachine.py history` on
real bars for that.

MIT. Original by [Jake Schincariol](https://opusjake.ai); prop firm edition by
AJ Hopkins. The original copyright notice is kept in `LICENSE`.
