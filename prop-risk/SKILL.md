---
name: prop-risk
description: >-
  Prop Firm Risk Manager. PASS or BLOCK every futures order against the firm's
  rules (trailing max loss, daily loss limit, max contracts) and the user's own
  (max loss per trade, daily loss, trades per day, reward to risk, entry window,
  news blackout), and keeps the account numbers those rules need in
  trader/account.json. Use when the user says "check it", "can I take this",
  "how much room do I have", "update my balance", "log that trade", "end of day".
---

# prop-risk

Not financial advice. A PASS means the order fits the limits written in
trader/config.json, not that it is a good trade. Nothing is sent from here;
the user still types yes in /prop-broker.

## Run

```
python3 "${CLAUDE_SKILL_DIR}/check.py" check                       # trader/orders.json -> trader/risk.json
python3 "${CLAUDE_SKILL_DIR}/check.py" account show
python3 "${CLAUDE_SKILL_DIR}/check.py" account set --balance 50250 --eod-high 50400
python3 "${CLAUDE_SKILL_DIR}/check.py" account trade --pnl -137.50     # after each trade closes
python3 "${CLAUDE_SKILL_DIR}/check.py" account eod --balance 50112.50   # after the session
```

`check` exits 1 when any order is blocked.

## The checks

- contracts within the plan's and your max (10 micros = 1 full-size)
- loss at the stop within your max loss per trade
- loss at the stop within what is left of your daily loss and the firm's daily
  loss limit, minus your buffer
- balance minus the loss stays above the trailing max loss floor plus the buffer.
  The floor is the end-of-day high minus `max_loss_limit`, and stops rising at the
  starting balance when `trail_stops_at_start` is true (`"trailing": "intraday"`
  moves the high on every trade instead)
- trades per day, minimum reward to risk, the entry window, a stale order date
- `news_events` within `news_blackout_minutes` (fill in real CPI, FOMC and jobs
  report times from an economic calendar; Topstep prohibits trading full size
  straight into scheduled major news)
- warnings: Live Funded stage (no API trading there), profit target reached

## Keep the account honest

The rules are only as good as the numbers: after each trade run `account
trade --pnl`, and after the session `account eod` with the balance TopstepX
shows. If they disagree, TopstepX is right; set it with `account set`.

## Hard rules

- Never edit the config to turn a BLOCK into a PASS for a trade in hand.
- The shipped limits are examples: the user copies the real ones from the
  Topstep dashboard, because firms change them.
