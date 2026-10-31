---
name: prop-scanner
description: >-
  Futures Watchlist Scanner for prop firm accounts (Topstep and similar). Runs the
  active strategy (ORB by default, see strategies/) on every contract in the
  watchlist (ES, MES, NQ, MNQ, YM, RTY, CL, GC and micros) and lists which are
  forming, waiting, triggered or expired, with entry, stop, target, ticks and
  dollars per contract. Use when the user says "scan", "what's setting up",
  "any ORB on ES or NQ", "check my watchlist", "scan futures".
---

# prop-scanner

Not financial advice. A scan is a list of contracts where the rule fired, not a
list of trades to take. Nothing here places an order: an order needs
/prop-risk to pass it and the user's own yes in /prop-broker.

## Run

```
python3 "${CLAUDE_SKILL_DIR}/scan.py"                                  # config symbols, now
python3 "${CLAUDE_SKILL_DIR}/scan.py" --symbols ES,NQ,MES,MNQ
python3 "${CLAUDE_SKILL_DIR}/scan.py" --now "2026-10-19 10:30" --offline trader/bars
python3 "${CLAUDE_SKILL_DIR}/scan.py" --write                          # -> trader/scan.json
```

- `--now` is New York time. Without it the real clock is used.
- `--offline` takes a bars file or a folder of `<SYMBOL>.json` / `.csv`
  (save ProjectX bars with `prop-broker/projectx.py bars MES --out trader/bars/MES.json`).
- `--strategy NAME` runs a different file from `strategies/` for this scan only.

## Read the result to the user

For each contract: the status and the one-line reason. For TRIGGERED, say the
side, entry, stop and target, the risk in ticks and dollars per contract, and
that the next step is /prop-entry (confirm on the platform) then /prop-exit.

## Data honesty

- Yahoo's futures bars (ES=F ...) are the continuous front month and can be
  delayed. Tell the user to check the price on TopstepX before acting.
- The scan only looks at the regular session (9:30 a.m. to 4:00 p.m. ET for
  equity index futures). Overnight bars are ignored.
- The strategy lives in `strategies/<name>.py`; the scanner never changes it.

## Hard rules

- Never call a scan result a recommendation.
- Never place, suggest placing or simulate placing an order from here.
