---
name: prop-budget
description: >-
  Futures Position Sizer for prop firm accounts. Sizes the plan in whole
  contracts from the user's max loss per trade, what is left of today's loss
  limits (theirs and the firm's), the room above the trailing max loss and the
  plan's contract limits; drops to the micro (ES to MES, NQ to MNQ) when one
  full-size contract does not fit. Writes one bracket order to trader/orders.json.
  Use when the user says "how many contracts", "size it", "can I afford ES".
---

# prop-budget

Not financial advice. Sizing writes an order to a file; it never sends it. The
order goes nowhere until /prop-risk passes it and the user types yes in
/prop-broker.

## Run

```
python3 "${CLAUDE_SKILL_DIR}/size.py"            # from trader/plan.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --write    # -> trader/orders.json
```

## The rule

contracts = the smallest of:
- `personal.max_loss_per_trade_usd` / risk per contract
- today's room: your daily loss, the firm's daily loss limit and the trailing
  max loss, each minus `personal.buffer_usd` / risk per contract
- `account.max_contracts` and `personal.max_contracts` (in full-size; 10 micros = 1)

If not even one full-size contract fits and the contract has a micro, it sizes
the micro at the same prices and says so. Fees per contract
(`fees_per_contract_round_trip`) are added to the risk.

## Tell the user

The order in plain words, the loss at the stop and gain at the target in
dollars, and what limited the size. If it is 0 contracts, say the stop is too
wide for today's limits and the trade is a skip, not a reason to raise limits.

## Hard rules

- Never raise a limit to make a trade fit.
- The account numbers must be the user's real plan numbers from the Topstep
  dashboard; the example config is an example.
