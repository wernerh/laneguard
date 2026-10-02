# Quickstart

This takes a repository from nothing to one dev lane running in `propose` mode (it opens PRs; you merge them). It assumes you have a GitHub repository, admin rights on it, and Python 3.10 or newer on the machine that runs `init`.

> **Pre-alpha.** The guard scripts (`lock.py`, `check.py`, `forge.py`, `history.py`, `allowlist.py`, `doctor.py`), the scaffold and `scripts/init.py` exist and have unit tests. The lane runs themselves have **not** been exercised end to end against live GitHub. The `/laneguard:*` commands are wired to these scripts; the equivalent script call is shown where useful. Do not point this at a repository you cannot afford to experiment on.

## 1. Install the plugin

```text
/plugin marketplace add wernerh/laneguard
/plugin install laneguard@laneguard
```

## 2. Scaffold your repository

In the repository, run `/laneguard:init`. It wraps `scripts/init.py`, which accepts these flags:

| Flag | Meaning | Default |
|---|---|---|
| `--profile minimal\|standard\|full` | `minimal` = dev lane; `standard` = dev + security; `full` = dev + security + design | `standard` |
| `--project NAME` | Project name (required) | |
| `--repo OWNER/NAME` | The repository (required) | |
| `--owner LOGIN` | An owner's GitHub login; repeat or comma-separate. A bot login is refused (required) | |
| `--approvals N` | Owner approvals needed for a gate; cannot exceed the number of owners | `1` |
| `--validation-lint`, `--validation-test`, `--validation-build` | Your lint, test and build commands. They become the validator's allowlisted commands | empty |
| `--ci none\|generic\|node\|python` | Also write a CI workflow from a template, or bring your own | `none` |
| `--engine-sha SHA` | Full 40-character commit SHA of the engine to pin (required) | |
| `--engine-repo OWNER/NAME` | Where the pinned engine is fetched from | `wernerh/laneguard` |
| `--run-max-minutes N` | Per-run cap; sets the workflow timeout and `lock_ttl_minutes = N + 15` | `30` |
| `--target DIR` | Directory to write into | `.` |
| `--force` | Overwrite existing files (without it, existing files are left alone and listed) | off |
| `--dry-run` | Print the files that would be written and write nothing | off |

The cautious first run:

```bash
python3 scripts/init.py --profile minimal --project my-project --repo me/my-project \
  --owner my-login --validation-test "npm test" --ci node \
  --engine-sha <40-hex commit of laneguard> --dry-run
```

Drop `--dry-run` to write. Init always starts in `mode: propose`. It writes `.laneguard/` (config, state, decisions, `plugin.lock`, `scaffold.version` with file hashes, a copy of the guard scripts), `.claude/settings.json` (the tool allowlist generated from the config), CODEOWNERS, the guard workflow, one workflow per lane, and the project docs. Commit it on a branch and merge it through a PR.

## 3. Set up the identity and protection

1. [Create the GitHub App](github-app.md) and store `LANEGUARD_APP_ID`, `LANEGUARD_APP_PRIVATE_KEY` and `ANTHROPIC_API_KEY`.
2. [Set branch protection or a ruleset](branch-protection.md) on the default branch, and protect `laneguard-data`.
3. Read how the [scheduler](scheduler.md) is wired and adjust the cron if you want.

## 4. Run `doctor`

```text
/laneguard:doctor
```

Equivalent: `python3 .laneguard/guard/doctor.py --as owner` (add `--json` for machine-readable output, `--offline` to skip GitHub). It reports PASS, WARN, FAIL or SKIP per check and exits non-zero on any FAIL. Fix every FAIL before continuing. A SKIP means it could not check something; under `--strict`, which lanes use before an `autonomous` run, a skipped critical check counts as a failure.

## 5. Design, then rehearse

```text
/laneguard:new "A CLI that converts invoices to CSV"     # brief -> spec -> plan, owner approval at each stage
/laneguard:run dev --dry-run                              # pause check, observer, triager, gatekeeper; writes nothing
```

## 6. The adoption ladder

Move up one step at a time, and only after reading what the lane produced.

| Mode | The lane may | Move up when |
|---|---|---|
| `observe` | Read the repository and write a report. No branches or PRs | Its reports match what you would have picked |
| `propose` (init default) | Open PRs. Never merge, even its own | You have reviewed its PRs for a while and would have merged most of them |
| `autonomous` | Merge its own labelled PRs after required checks pass | `doctor --strict` passes, `laneguard-review` is a required check, and you accept the residual risk in the [security model](../security-model.md) |

Raising a mode is a change to `.laneguard/config.yaml`, a protected path, so it is always an owner PR; a lane cannot raise its own mode. A lane in `autonomous` mode refuses to run unless `doctor --strict --as lane` passes. Before using `autonomous`, read the CODEOWNERS note in [branch protection](branch-protection.md).

## 7. Going back

**Pause.** `/laneguard:pause [lane]` creates `.laneguard/PAUSED` (all lanes) or `.laneguard/PAUSED.<lane>`; commit it to the default branch so scheduled runs see it. Every run checks for pause flags first and exits. The circuit breaker and the cost ceiling pause a lane themselves, through `history.py`, which writes the flag on the `laneguard-data` branch. Pausing needs no approval.

**Unpause.** Removing a flag is owner-only. `/laneguard:resume [lane]` handles flags in the working tree and tells you to commit the removal through your own branch protection; for flags the breaker wrote on `laneguard-data`, use `python3 .laneguard/guard/history.py unpause --lane <lane>` (omit `--lane` for the global flag), which refuses callers who are not configured owners. Look at the `needs-human` issue the breaker opened before you do.

**Lower the mode.** Set `mode: observe` (or `propose`) in `.laneguard/config.yaml` through a PR.

**Stop everything immediately.** Disable the lane workflows in the Actions tab, or uninstall the GitHub App from the repository. The bot can no longer mint new tokens (a token already issued expires within an hour).

**Eject.** `/laneguard:eject` (script: `scripts/eject.py`) vendors the skills, agents and commands into `.claude/` as an owner-reviewed PR. `.laneguard/plugin.lock` is kept with `vendored: true` as provenance rather than removed. To drop Laneguard entirely, remove the workflows, `.laneguard/` and the allowlist by hand in a PR and uninstall the App.
