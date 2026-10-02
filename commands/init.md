---
description: Scaffold Laneguard into the current repo (config, guard scripts, workflows, allowlist, engine pin)
argument-hint: "[--profile minimal|standard|full] [--project NAME] [--repo owner/name] [--owner LOGIN ...] [--ci none|generic|node|python] [--dashboard]"
---

Scaffold Laneguard into the current repository. Arguments: $ARGUMENTS

1. Gather what `scripts/init.py` needs, asking the owner only for what is missing: project name, `owner/name` (from `git remote get-url origin` if possible), owner GitHub login(s) (never a bot), profile (default `standard`), the lint/test/build commands, and CI (`none` if they already have CI).
2. Resolve the engine commit to pin: the full 40-character SHA of the installed engine (`git -C "${CLAUDE_PLUGIN_ROOT}" rev-parse HEAD`). If it cannot be determined, ask the owner for the SHA. Never pin a branch or tag.
3. Preview first: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/init.sh" --dry-run <flags>` and show the file list. Then run it for real with `--engine-sha <sha> --plugin-root "${CLAUDE_PLUGIN_ROOT}"`. Existing files are left alone unless the owner asks for `--force`.
4. Run `python3 .laneguard/guard/doctor.py --offline` and show the result.
5. Tell the owner the remaining steps, in this order: commit the scaffold on a branch and open a PR; create the GitHub App and set secrets (`docs/setup/github-app.md`); set branch protection (`docs/setup/branch-protection.md`); then run `/laneguard:doctor` online. State clearly that init starts every lane in `mode: propose`, that nothing is enforced on GitHub until branch protection is set, and that it did not touch GitHub settings.

Do not edit generated protected files by hand afterwards.
