---
description: Remove a pause flag. Owner only
argument-hint: "[lane]"
---

Resume Laneguard. Argument (optional lane name): $ARGUMENTS

Removing a pause flag is owner-only, and a lane never removes its own.

1. Refuse in scheduled or unattended runs, or when no owner is present.
2. Show what is paused and why: `python3 .laneguard/guard/history.py status --no-trip`. If the circuit breaker paused a lane, say what tripped it and ask the owner to confirm they have read the `needs-human` issue.
3. After the owner confirms, run `python3 .laneguard/guard/history.py unpause [--lane <lane>]`. It verifies through the forge that the caller is a configured owner and a real person (not a bot); if it refuses, report that and stop. Do not try another route.
4. Also check for owner-set flags in the working tree (`.laneguard/PAUSED*`); removing those is a protected-path change the owner commits through branch protection, so tell them rather than doing it.
