---
description: Stop depending on the plugin by vendoring skills, agents and commands into .claude/ (owner-reviewed PR)
argument-hint: ""
---

Eject from the plugin. This writes `.claude/**` and lane workflows, which are protected paths, so it is owner-only and always ends in a PR for review.

1. Confirm the person is an owner and that this is an interactive session.
2. Explain what changes: skills, agents and commands are copied into `.claude/` (commands become `/laneguard-<name>`; `init`, `migrate` and `eject` are not vendored because they need the plugin checkout, and `doctor` loses `--engine-root`); lane workflows stop checking out the pinned engine; if the dashboard workflow exists, `dashboard/build.py` is vendored into `.laneguard/dashboard/` and the workflow rewritten to use it; `.laneguard/plugin.lock` stays as provenance with `vendored: true` (it still records a full SHA); you will no longer receive engine updates except by re-vendoring. The script prints a changelog saying exactly this; show it to the owner.
3. Dry run: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/eject.py" --engine-sha <sha>` where `<sha>` is the engine commit (`git -C "${CLAUDE_PLUGIN_ROOT}" rev-parse HEAD`).
4. After the owner agrees: branch `laneguard-eject`, re-run with `--apply`, run `python3 .laneguard/guard/doctor.py --offline`, commit, push, open a PR with `forge.py write pr`. Never merge it.
