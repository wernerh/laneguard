# Scheduling lanes

A lane run starts when something calls `/laneguard:run <lane>`. The scheduler is an adapter, and the payload is always that one line, so the behaviour lives in the version-pinned skills and not in an editable prompt.

> Status: pre-alpha. The workflow template exists and `doctor` checks its wiring, but it has not been exercised end to end against live GitHub Actions.

## Default: GitHub Actions cron

`init` renders one workflow per lane, `.github/workflows/laneguard-lane-<lane>.yml`, from `templates/github/workflows/laneguard-lane.yml.tmpl`. It is a protected path (owners only).

What the rendered workflow does:

1. Runs on `schedule` (cron) and `workflow_dispatch` (so you can start a run by hand).
2. Mints the bot's installation token with `actions/create-github-app-token` from `LANEGUARD_APP_ID` and `LANEGUARD_APP_PRIVATE_KEY` ([setup](github-app.md)).
3. Checks out your repository, then checks out the engine at the commit in `.laneguard/plugin.lock`, so the run uses the pinned engine and not whatever is newest.
4. Runs `anthropics/claude-code-action` with the prompt `/laneguard:run <lane>`, the engine as `--plugin-dir`, and `ANTHROPIC_API_KEY`.

### Cron expressions

`init` converts each lane's `schedule` from `config.yaml` (`every Nh`, `every Nm`, `daily`, `weekly`) into a cron expression and staggers the start minute per lane (7, 18, 29, ...) so lanes do not all fire on the hour. With the default lane schedules that gives, for example, `7 */2 * * *` for `dev` and `18 */4 * * *` for `security`. Cron times are UTC. GitHub does not run a schedule more often than every 5 minutes, and `init` rejects `every Nm` below 5.

`schedule` in `config.yaml` is an input to `init`; the workflow's cron line is what actually runs. If you edit one, edit the other, through an owner-reviewed PR (both are protected paths). `doctor` checks that a cron line exists, not that it equals the config schedule.

### Drift tolerance

GitHub's scheduled workflows are best effort. Runs can start minutes late under load, and a run can occasionally be skipped. Laneguard tolerates this by design:

- **Late start.** Nothing depends on the exact minute. The lock, claims and heartbeats are measured against server time, not against when the job was supposed to start.
- **Skipped run.** The lane simply does not run that slot. A quiet or missing run is not an error and does not count toward the circuit breaker.
- **Two runs close together.** The lock allows one holder at a time. A second run that finds a fresh lock held by another run stops quietly.

Two GitHub behaviours to know about:

- Scheduled workflows run only from the **default branch**.
- On public repositories, GitHub disables scheduled workflows after a period (currently 60 days) with no repository activity. Re-enable them in the Actions tab if lanes go quiet on an idle repository.

### Concurrency and timeouts, and how they line up with config

All timings derive from the `limits` block of `.laneguard/config.yaml`:

| Setting | Default | Where it must agree |
|---|---|---|
| `limits.run_max_minutes` | 30 | The workflow's `timeout-minutes`. `doctor` fails the `workflows` check if they differ |
| `limits.lock_ttl_minutes` | 45 (run max + 15) | Must be greater than `run_max_minutes`; config validation enforces this |
| `limits.heartbeat_minutes` | 10 | At most half of `lock_ttl_minutes`; config validation enforces this |
| `budgets.per_run.max_turns` | 60 | The `--max-turns` value in `claude_args` of the workflow. The template hardcodes 60, and `doctor` does **not** compare them. If you change one, change the other in an owner-reviewed PR |
| workflow `concurrency.group` | `laneguard-<lane>`, `cancel-in-progress: false` | `doctor` fails the `workflows` check if the group is missing |

The concurrency group serialises runs of the **same lane**: GitHub keeps at most one running and one pending job per group, and `cancel-in-progress: false` means a new run waits instead of killing a live one. It does not coordinate different lanes; that is the job of the git-ref lock (`lock.py`), which is also what protects against a run started by a different scheduler.

If you raise `run_max_minutes`, raise `lock_ttl_minutes` with it (keep it above the run maximum) and update `timeout-minutes`. A timeout shorter than the lock TTL is deliberate: a job killed by the runner leaves a lock that becomes stale after the TTL and is taken over by the next run (and the guard check alarms when a lock is older than twice the TTL).

## Optional: Claude Code scheduled tasks

If you prefer Claude Code's own scheduled tasks (cloud) over GitHub Actions, set `scheduler.adapter` to something other than `github-actions` in `config.yaml` and schedule the same single line, `/laneguard:run <lane>`, per lane.

What you take on:

- **`doctor` cannot verify it.** It reports a WARN (`scheduler`) that you should check the schedule by hand, and it only verifies the Actions workflows when the adapter is `github-actions`. Note that `doctor` also expects the lane workflow files to exist; if you do not use Actions for lanes, expect `workflows` findings you will need to interpret.
- **Identity.** The task must run with the bot's installation token, not your own. A run that resolves to an owner's token fails the `doctor --as lane` check. Check how your scheduled task obtains credentials before relying on it.
- **Limits.** Align the task's own time limit with `limits.run_max_minutes`; Laneguard's per-run caps (turns, tokens) still apply through the config, but the scheduler's timeout is yours to set.
- **Same payload, same lock.** Because the lock is a git ref, a lane started from Actions and one started from a scheduled task still exclude each other.

This adapter is described in the design but is the less tested path. Start with Actions.

## Checking it works

```bash
python3 .laneguard/guard/doctor.py --offline    # workflows: pinned actions, minimal permissions, timeout and concurrency present
```

Then trigger one run by hand (Actions tab > the lane workflow > **Run workflow**) with the lane in `observe` or `propose` mode and read the report it writes.
