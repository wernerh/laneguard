---
description: Open an owner-reviewed PR that patches engine-managed scaffold files to a newer engine version
argument-hint: "[--engine-sha SHA] [--overwrite-conflicts]"
---

Migrate the scaffold to the installed engine version. Arguments: $ARGUMENTS

This writes protected paths, so it is an owner action: confirm the person is an owner (`python3 .laneguard/guard/forge.py whoami` and `permission`), and refuse in scheduled or unattended runs.

1. Resolve the new engine SHA (the argument, else `git -C "${CLAUDE_PLUGIN_ROOT}" rev-parse HEAD`). It must be a full 40-character SHA.
2. Dry run: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/migrate.py" --engine-sha <sha> --plugin-root "${CLAUDE_PLUGIN_ROOT}"`. Show the changelog. Files the project edited since init are conflicts and are left alone; a locally edited guard script is serious, so say so plainly.
3. After the owner agrees, create a branch `laneguard-migrate/<version>`, re-run with `--apply`, run `python3 .laneguard/guard/doctor.py --offline`, commit, push the branch and open a PR with `forge.py write pr`, using the changelog as the body.
4. Never merge it. The checker requires an owner for these paths and branch protection requires owner review.
