---
name: prop-entry
description: >-
  Futures Entry Timer for prop firm accounts. Watches one contract bar by bar and
  says whether the active strategy (ORB by default) is forming, waiting,
  triggered or expired, using your entry window from trader/config.json. Use when
  the user says "is ES triggering", "watch MNQ", "tell me when to get in",
  "check the ORB on NQ", "has it broken out".
---

# prop-entry

Not financial advice. This tells the user what the rule says; it does not
enter anything. Every order still needs /prop-risk to pass it and the user's
own yes in /prop-broker.

## Run

```
python3 "${CLAUDE_SKILL_DIR}/entry.py" check MES
python3 "${CLAUDE_SKILL_DIR}/entry.py" check ES --now "2026-10-19 10:30" --offline trader/bars --write
python3 "${CLAUDE_SKILL_DIR}/entry.py" watch MNQ --every 30 --write      # until triggered or expired
```

`--write` saves the verdict to `trader/entry.json`, which /prop-exit reads.

## Statuses

| status    | meaning |
|-----------|---------|
| pre-open  | before the regular session |
| forming   | the strategy is still building its levels (ORB: the opening range) |
| waiting   | levels set, no signal yet |
| triggered | a bar closed through the level inside the entry window |
| expired   | no signal by `no_entries_after` |
| closed    | weekend or holiday |

## Tell the user

- On TRIGGERED: the side, the trigger bar's close time, entry, stop, target,
  ticks and dollars per contract. Then: confirm the price on TopstepX (Yahoo can
  lag), and run /prop-exit to lock the plan before entering.
- On WAITING: how far the last close is from the level.
- A signal that fired before `no_entries_before` is skipped on purpose.

## Hard rules

- Never enter, never say "buy now". Say what the rule shows.
- Yahoo data can be delayed; say so whenever timing matters.
