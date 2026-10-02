---
description: Summarise lane state, pause flags, open decisions, open PRs and engine versions
---

Report the current Laneguard state of this repository. This command only reads; it changes nothing.

Gather what exists and skip what does not:

- `.laneguard/config.yaml`: project, owners, profile, mode, and each lane's mode, label and schedule. If it is missing, say the project is not initialised.
- Pause state: `.laneguard/PAUSED` and any `.laneguard/PAUSED.<lane>` files.
- `.laneguard/state.yaml`: last run per lane, claims, circuit breaker state.
- `.laneguard/decisions.yaml`: open owner decisions.
- Open PRs and issues per lane label, and any `needs-human` issues (use `gh`; if it is unavailable or unauthenticated, say so).
- Run history and budget used against `budgets.monthly_cost_ceiling_usd`, from `runs.jsonl` on the `laneguard-data` branch if it exists.
- Engine pin from `.laneguard/plugin.lock` against the installed plugin, and `.laneguard/scaffold.version`.

Present it as a short plain summary, one line per lane, then open decisions. Say plainly what is not available yet in this preview rather than showing blanks.
