---
description: Run one lane once (dev, security or design). Use --dry-run to rehearse without changing anything
argument-hint: <lane> [--dry-run]
---

Run one Laneguard lane run. Arguments: $ARGUMENTS

1. Parse the lane name (as defined in `.laneguard/config.yaml`) and the `--dry-run` flag. If the lane is missing or unknown, list the configured lanes and stop.
2. Read the `core` skill, then the matching lane skill (`dev-lane`, `security-lane`, `design-lane`), and follow them. `core` is the run protocol and names the exact guard command for each step; the lane skill supplies parameters.
3. **Dry run** (`--dry-run`): run the pause check (`history.py pause-check`, read only: do not let it create a pause), observer, triager and gatekeeper only. Write nothing, take no lock, create no branches, PRs, issues, comments or history records. Print the report in this session in the style of:

   ```
   lock          would acquire
   observer      <state summary>
   triager       <issue>: <STATUS>
   gatekeeper    <issue>: <VERDICT>
   would do      <task, branch name>
   ```

4. **Real run** (no `--dry-run`): requires `.laneguard/config.yaml` and the guard scripts in `.laneguard/guard/`. If anything is missing, name it and offer a dry run. For a lane in `autonomous` mode, `doctor.py --strict --as lane` must pass first (core, section 0). Do not improvise a lock or any other guard.

Never raise the lane's mode, edit protected paths, or continue past a `BLOCK`, `UNTRUSTED` or `SUSPICIOUS` result.
