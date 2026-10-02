# Changelog

All notable changes to Laneguard are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project intends to follow [Semantic Versioning](https://semver.org/) once it has a stable release. Until then, anything can change.

## [Unreleased]

## [0.1.0] - unreleased

Pre-alpha. Nothing here has been run end to end against live GitHub. This entry lists what exists in the repository, not what has been proven in use.

### Added

- Design spec (draft v2) with threat model and enforcement table: [`docs/design-spec.md`](docs/design-spec.md).
- Ten subagent definitions in `agents/`: architect, planner, observer, triager, gatekeeper, implementer, validator and three reviewers (dev, security, design).
- Skills: `intake`, `spec`, `plan`, `core`, and the three lane skills (`dev-lane`, `security-lane`, `design-lane`).
- Commands: `new`, `run`, `status`, `pause`, `resume`, `init`, `doctor`, `migrate`, `eject`. Command wiring to the guard scripts is still being finished; `migrate` and `eject` are not built.
- Plugin and marketplace manifests, and logo assets.
- Guard scripts (Python 3, standard library only) in `guard/`, each with unit tests in `guard/tests/`:
  - `lock.py`: atomic lock as a git ref, compare-and-swap pushes, leases and heartbeats, forge-supplied time.
  - `check.py`: the pull-request checker (protected paths, weakened checks, secret patterns, stale lock, engine pin, lane scope).
  - `forge.py`: GitHub adapter with a write allowlist, issue trust, owner approval verification and the `laneguard-review` status.
  - `history.py`: run history, pause flags, circuit breaker and cost ceiling on the `laneguard-data` branch.
  - `allowlist.py`: generates and verifies the tool allowlist in `.claude/settings.json`.
  - `doctor.py`: preflight that reports whether guarantees are actually in place.
  - `laneconfig.py`: dependency-free config parser and validator.
- Scaffold: `scripts/init.py` / `init.sh` and `templates/` (config, state, CODEOWNERS, guard and per-lane workflows, CI templates, project docs), with tests in `scripts/tests/`. Actions are pinned to full commit SHAs.
- Eval suite scaffolding in `evals/` (injection corpus, fixture repositories, scorer, offline tests). No results from live agent runs have been published.
- Documentation: setup guides for the [GitHub App](docs/setup/github-app.md), [branch protection](docs/setup/branch-protection.md), the [scheduler](docs/setup/scheduler.md) and a [quickstart](docs/setup/quickstart.md); a [security model](docs/security-model.md); drafts for the launch in `docs/launch/`.
- Repository hygiene: issue and pull request templates, CI for this repository (tests on Python 3.10 to 3.13), contributing and security policies.

### Known limits

- Lane runs have not been exercised end to end against live GitHub.
- Permission scoping is not a sandbox. The reviewer verdict status is posted by the lane's own token, so reviewer independence is model and context separation, not identity. See [`docs/security-model.md`](docs/security-model.md).
- Some budget limits (`max_tokens`, open-PR and issue caps) are carried by skills, not enforced by scripts.
