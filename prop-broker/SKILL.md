---
name: prop-broker
description: >-
  Prop Firm Order Ticket and TopstepX/ProjectX bridge. Shows each sized order in
  plain words, records the user's exact yes, and (on the user's own computer
  only) sends a market entry with stop and target brackets through the ProjectX
  API, dry run by default. Use when the user says "place it", "send it to
  Topstep", "show the ticket", "connect TopstepX", "flatten", "get me out".
---

# prop-broker

Not financial advice. No order goes out until /prop-risk passed that exact
order and the user typed yes for it. API orders on TopstepX are final: no
review, adjustment or reversal.

## Topstep rules for this skill

- **Your computer only.** Topstep's Terms of Use prohibit trading from a VPS,
  VPN or remote server. A cloud Claude session counts. `projectx.py place` and
  `flatten` must run in a terminal on the user's own machine (Claude Code
  running locally is fine).
- **Not on Live Funded.** Topstep does not allow API trading on Live Funded
  accounts. There, read the ticket and enter it by hand on TopstepX.
- **API access** is a separate TopstepX subscription. Brackets need Auto OCO
  Brackets turned on in TopstepX risk settings.
- **Practice first.** Run the whole flow on a Practice account before a Combine.

## Flow

```
python3 "${CLAUDE_SKILL_DIR}/ticket.py" show                           # READY / BLOCKED / NOT CHECKED
python3 "${CLAUDE_SKILL_DIR}/ticket.py" confirm --index 1 --reply "<the user's reply, word for word>"
python3 "${CLAUDE_SKILL_DIR}/projectx.py" place --index 1 --account-id ID          # dry run: prints the request
python3 "${CLAUDE_SKILL_DIR}/projectx.py" place --index 1 --account-id ID --send   # user types yes again in the terminal
python3 "${CLAUDE_SKILL_DIR}/ticket.py" result --index 1 --status filled --filled-price 6712.75
```

1. Show the ticket text to the user exactly as `ticket.py show` prints it.
2. Ask: "Type yes to approve this exact order." Pass their reply verbatim to
   `confirm`. Only an exact "yes" approves, and it lasts 15 minutes.
3. `place` re-checks READY and the yes, prints the request, and sends only with
   `--send` plus a second typed yes in the terminal. It refuses accounts the API
   reports as not simulated.

## Setup on the user's computer

```
export PROJECTX_USERNAME="your TopstepX username"
export PROJECTX_API_KEY="the key from TopstepX Settings > API"
python3 prop-broker/projectx.py accounts        # find the account id (Practice or Combine)
python3 prop-broker/projectx.py contract MES    # the live contract id, tick size and value
```

Keys live in environment variables, never in a chat and never in a file in
the repo. If a key is pasted in a chat, tell the user to delete it and make a
new one.

## Bracket format

A market entry (`type` 2) with `stopLossBracket {ticks, type 4}` and
`takeProfitBracket {ticks, type 1}`, ticks as positive counts from the entry.
If a Practice test shows your API version wants a signed stop, use
`--signed-ticks`.

## Hard rules

- Never send without the user's typed yes for that exact ticket.
- Never run `--send` or `flatten` from a cloud session.
- Never use the API on a Live Funded account.
- Never store or echo API keys.
