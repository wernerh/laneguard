---
description: Remove a pause flag. Owner only
argument-hint: "[lane]"
---

Resume Laneguard. Argument (optional lane name): $ARGUMENTS

Removing a pause flag is a protected-path change and is owner-only.

1. Refuse if this is a scheduled or unattended run, or if no owner is present in this session. A lane never removes its own pause flag.
2. Identify the person: `gh api user --jq .login`. It must match a login in `owners:` in `.laneguard/config.yaml`. If the config is missing or the login does not match, stop and say why.
3. Show which flags exist (`.laneguard/PAUSED`, `.laneguard/PAUSED.<lane>`) and the reason recorded in each. If a lane was paused by its circuit breaker, say what tripped it and ask the owner to confirm they have looked at the `needs-human` issue.
4. After the owner confirms, delete the named flag(s) in the working tree. Do not commit, push or open a PR yourself. Tell the owner to commit the removal through their own branch protection, because the checker only accepts this change from an owner login.
