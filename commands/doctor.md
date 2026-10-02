---
description: Check that the guarantees are actually enforced (config, pin, guard hashes, CODEOWNERS, allowlist, workflows, branch protection)
argument-hint: "[--offline] [--strict] [--as owner|lane]"
---

Run the doctor. Arguments: $ARGUMENTS

Run `python3 .laneguard/guard/doctor.py $ARGUMENTS --engine-root "${CLAUDE_PLUGIN_ROOT}"` (add `--json` if you need to parse it) and report exactly what it printed: each check's status and detail, then the summary line. Do not soften or reinterpret a FAIL, and never describe a SKIP as a pass.

- A FAIL means a guarantee is not enforced. List the fix for each from `docs/setup/` (branch protection, GitHub App) or by re-running init/migrate.
- A SKIP means it could not be checked, usually the online checks without a token that can read branch protection. Say which and how to run it with the right token.
- Run as the person (an owner token) to read branch protection; run with `--as lane` and the lane's bot token to verify the bot has no admin or maintain rights. A single run cannot do both, so say which one this was.
- If `.laneguard/guard/doctor.py` does not exist, the project is not initialised: point to `/laneguard:init`.

This command only reads.
