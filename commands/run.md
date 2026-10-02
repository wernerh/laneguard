---
description: Run one lane once (dev, security or design). Use --dry-run to rehearse without changing anything
argument-hint: <lane> [--dry-run]
---

Run one Laneguard lane run. Arguments: $ARGUMENTS

1. Parse the lane name (`dev`, `security` or `design`, or another lane defined in `.laneguard/config.yaml`) and the `--dry-run` flag. If the lane is missing or unknown, list the configured lanes and stop.
2. Read the `core` skill, then the matching lane skill (`dev-lane`, `security-lane`, `design-lane`), and follow them. `core` is the run protocol; the lane skill supplies parameters.
3. **Dry run** (`--dry-run`): run the pause check, observer, triager and gatekeeper only. Write nothing, take no lock, create no branches, PRs, issues or comments. Print the report in this session in the style of:

   ```
   lock          would acquire
   observer      <state summary>
   triager       <issue>: <STATUS>
   gatekeeper    <issue>: <VERDICT>
   would do      <task, branch name>
   ```

4. **Real run** (no `--dry-run`): only if `.laneguard/config.yaml` and all of `.laneguard/guard/lock.py`, `check.py` and `forge.py` exist. If any is missing, say exactly which, say that real runs are not available in this preview, and offer a dry run instead. Do not improvise a lock or any other guard.

Never raise the lane's mode, edit protected paths, or continue past a `BLOCK`, `UNTRUSTED` or `SUSPICIOUS` result.
