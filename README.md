<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <img src="assets/logo-light.svg" alt="Laneguard" width="420">
  </picture>
</p>

<p align="center"><b>Autonomous dev lanes with a leash.</b></p>

<p align="center">
  A Claude Code plugin that turns an idea into an approved design, then runs scheduled, gated agents ("lanes") that open pull requests for you, while enforcing the limits <i>outside the prompt</i>.
</p>

> **Status: pre-alpha. The design is complete and the engine scripts exist; lane runs have not been exercised end to end against live GitHub.**
> What exists today: the [design spec](docs/design-spec.md), ten [subagent definitions](agents/), seven [skills](skills/), nine [commands](commands/), the plugin and marketplace manifests, the logo, and the engine scripts: the guard scripts in [`guard/`](guard/) (`lock.py`, `check.py`, `forge.py`, `history.py`, `allowlist.py`, `doctor.py`), the scaffold generator [`scripts/init.py`](scripts/init.py) and the [`templates/`](templates/) it renders. Their unit tests pass. Wiring the slash commands to those scripts is still being finished, and nothing has been run against a live GitHub repository as part of a full lane run, so the guarantees below are tested against fakes and local git, not proven in use. Usage examples below show the intended behaviour and are marked as such. Do not run this against a repository you care about yet. See the [roadmap](#roadmap).

---

## Contents

- [Why Laneguard](#why-laneguard)
- [How it works](#how-it-works)
- [Install the preview](#install-the-preview)
- [Quick start (planned)](#quick-start-planned)
- [Usage examples (planned)](#usage-examples-planned)
- [Configuration](#configuration)
- [Agents](#agents)
- [Security](#security)
- [Documentation](#documentation)
- [How it compares](#how-it-compares)
- [Roadmap](#roadmap)
- [Repository layout](#repository-layout)
- [Contributing](#contributing) · [License](#license)

---

## Why Laneguard

Agents that open pull requests on a schedule are useful, and risky in predictable ways: they read untrusted text (issues, comments), they hold credentials, they can loop, and a model that is asked nicely not to edit its own rules can still be talked into it.

Laneguard's position is that **prompts are not a security boundary**. It adds a small control plane around scheduled agents:

| Problem with unattended agents | What Laneguard does |
|---|---|
| Two scheduled runs collide, or a crashed run blocks everyone | One atomic lock with leases and heartbeats; stale locks recovered automatically |
| The agent edits its own protocol, reviewer or limits | Protected paths, owner-only changes, enforced by CODEOWNERS and a CI checker |
| Issue text steers the agent (prompt injection) | A read-only *triager* turns untrusted text into a structured brief; the writing agent never sees the raw text |
| "Human approval" is a sentence in a prompt | Gates enforced by token scope, tool allowlists, branch protection and CI |
| Runaway cost or loops | Per-run and monthly budgets, a circuit breaker, caps on open PRs, and a pause switch |
| The same model writes and reviews its own code | An independent, read-only reviewer with a fresh context and (by default) a different model |
| All-or-nothing trust | An adoption ladder: `observe`, then `propose` (PRs only), then `autonomous` (merges its own PRs) |

It also includes a design-first pipeline (brief, then spec and ADRs, then a phased plan) so the agents implement an approved plan rather than guessing.

## How it works

```
                    owner approves brief, spec, plan  (GitHub: /approve)
                                    |
  /laneguard:new  ->  intake -> architect -> planner  ->  roadmap issues (next phase only)
                                    |
        scheduler (GitHub Actions cron) calls:  /laneguard:run <lane>
                                    |
  pause check -> LOCK -> observer -> triager -> gatekeeper -> implementer
                         (read-only) (firewall)  (gates)     (only writer)
                                    |
              validator -> reviewer (independent, read-only) -> PR
                                    |
              propose mode: stop here.   autonomous mode: merge own PR after required checks
                                    |
                      report -> run history -> UNLOCK
```

**Lanes** are independent scheduled workers, each with its own label, owned paths, reviewer and schedule. Defaults: `dev`, `security`, `design`. A lane run does **one major task**, and a quiet run (nothing worth doing) counts as a success.

**Two parts in one repo:**

- **Engine** (this plugin): skills, agents, commands, guard scripts. Projects pin it to a commit SHA, so an upstream change can never silently alter the rules of an unattended agent.
- **Scaffold** (copied into your repo by `init`): config, state, decisions, CI guard workflow, CODEOWNERS. After init, your project owns these files.

Full details are in the [design spec](docs/design-spec.md).

## Install the preview

This repository is its own Claude Code marketplace:

```text
/plugin marketplace add wernerh/laneguard
/plugin install laneguard@laneguard
```

**What works in the 0.1 preview**

| Piece | State |
|---|---|
| The ten subagents (`laneguard:architect`, `laneguard:triager`, and so on) | Available |
| `/laneguard:new "<idea>"` | Works: intake, spec and plan, with owner approval at each stage |
| `/laneguard:run <lane> --dry-run` | Works: pause check, observer, triager and gatekeeper only; writes nothing |
| `/laneguard:init`, `doctor`, `migrate`, `eject` | Wired to `scripts/init.py`, `guard/doctor.py`, `scripts/migrate.py`, `scripts/eject.py`; scripts are unit tested, not yet used on a live repository |
| `/laneguard:status`, `/laneguard:pause`, `/laneguard:resume` | Wired to `history.py` and `lock.py` (pause flags live on the `laneguard-data` branch) |
| `/laneguard:run <lane>` without `--dry-run` | Wired to `lock.py`, `forge.py`, `history.py` and `doctor.py`; **lane runs have not been exercised end to end against live GitHub** |

The engine scripts exist and their tests pass, but the guarantees in [Security](#security) have not been verified against a live repository, so read them as tested design, not a track record. In the design pipeline, owner approval before `init` is an in-session confirmation recorded in the document as unverified; once a project is initialised the GitHub `/approve` flow in `forge.py` is used instead. It is unit tested, not yet used in a live run.

## Quick start

> The commands are wired to the scripts, but nothing here has run against a live repository yet; see [Install the preview](#install-the-preview) and the [quickstart](docs/setup/quickstart.md).

```text
# 1. Add the marketplace and install the plugin
/plugin marketplace add <owner>/laneguard
/plugin install laneguard

# 2. In an empty or existing repo: scaffold, in the safest mode
/laneguard:init --profile minimal        # one dev lane, mode: propose

# 3. Verify the guarantees are actually enforced
/laneguard:doctor

# 4. Design the project (three owner approvals)
/laneguard:new "A CLI that converts invoices to CSV"

# 5. Rehearse a lane without changing anything
/laneguard:run dev --dry-run
```

`doctor` fails loudly if a guarantee in the [Security](#security) section is not actually in place (token scopes, branch protection, CODEOWNERS, allowlists, scheduler wiring). Lanes refuse to run in `autonomous` mode until it passes.

## Usage examples (planned)

Output shown is illustrative.

### 1. Design a project

```text
> /laneguard:new "A CLI that converts invoices to CSV"

Intake        wrote docs/BRIEF.md             -> comment "/approve brief" on the PR
Spec          wrote PRODUCT.md, ARCHITECTURE.md, docs/adr/0001-language.md
                                              -> comment "/approve spec"
Plan          wrote docs/WORKPLAN.md (3 phases, Phase 1 = walking skeleton)
                                              -> comment "/approve plan"
Handoff       opened 4 issues for Phase 1; PROJECT_STATE.md next action set
```

Approval is a GitHub comment from a login listed in `owners:`, verified through the API. Issues for Phase 2 open only after the Phase 1 gate is approved.

### 2. Rehearse a lane (dry run)

```text
> /laneguard:run dev --dry-run

lock          acquired (dry run: not written)
observer      2 open issues, CI green, 0 stale claims
triager       #12 OK, #14 NEEDS_CRITERIA (plan has none)
gatekeeper    #12 PASS
would do      implement #12 "Add --delimiter flag" on branch laneguard/12-delimiter-flag
report        written to laneguard-data; no branches, PRs or comments created
```

### 3. Schedule the lanes

The scheduler is an adapter. The default is a GitHub Actions cron job whose payload is a single line. Illustrative workflow (the shipped template will be tested before release):

```yaml
# .github/workflows/laneguard-lane.yml  (protected path)
name: laneguard-dev
on:
  schedule: [{ cron: "0 */2 * * *" }]
  workflow_dispatch: {}
permissions:
  contents: read            # the lane's own credentials come from the bot identity, not this token
concurrency: laneguard-dev
jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 30     # matches limits.run_max_minutes
    steps:
      - uses: actions/checkout@<full-commit-sha>
      - uses: anthropics/claude-code-action@<full-commit-sha>
        with:
          prompt: "/laneguard:run dev"
```

Because the schedule only says `/laneguard:run dev`, the behaviour lives in version-pinned skills, not in an editable prompt, so there is no prompt drift.

### 4. A gate stopping a lane

```text
needs-human  #31  "Add Stripe webhook handler"
  gate:      spending money / external service credentials
  reason:    task requires creating a payment-provider account and storing an API key
  decision:  Approve the account setup yourself, then comment "/approve gate-31".
  agent:     gatekeeper (BLOCK). The lane picked other work and did not retry.
```

### 5. The checker stopping a protected-path edit

```text
laneguard-guard / check  FAILED
  .laneguard/config.yaml  modified by laneguard-bot (not an owner)
  Protected paths can only be changed by an owner via a needs-human PR.
```

### 6. Pause, status, resume

```text
> /laneguard:status
mode: propose   lanes: dev (last run 38m ago, quiet), security (paused: 3 failed runs)
budget: $41 of $200 this month   open PRs: dev 1, security 0   open decisions: 2
engine pin: 3f9a1c2 (latest 0.4.0)   scaffold: 0.3.1

> /laneguard:pause            # creates .laneguard/PAUSED; every lane checks it first
> /laneguard:resume           # owner-only (protected path)
```

### 7. Climb the adoption ladder

Start with `observe` (reports only), move to `propose` (PRs, you merge), and only later to `autonomous`. Raising a mode is a protected-path change, so it is always an owner-reviewed PR:

```yaml
lanes:
  dev: { label: laneguard, schedule: "every 2h", owns: [PROJECT_STATE.md], mode: autonomous }
```

## Configuration

Everything lives in `.laneguard/config.yaml`. Illustrative:

```yaml
project: acme-billing
repo: acme/acme-billing
owners: [your-github-login]        # who can approve gates and change protected paths
approvals_required: 1

profile: standard                  # minimal | standard | full
mode: propose                      # observe | propose | autonomous  (per-lane override allowed)

lanes:
  dev:      { label: laneguard,          schedule: "every 2h", owns: [PROJECT_STATE.md], mode: propose }
  security: { label: laneguard-security, schedule: "every 4h", owns: [docs/security/],  mode: propose }

limits:                            # every timing is derived from this block
  run_max_minutes: 30
  lock_ttl_minutes: 45             # run_max + 15
  heartbeat_minutes: 10
  claim_expiry_hours: 24

budgets:
  per_run: { max_turns: 60, max_tokens: 2000000 }
  monthly_cost_ceiling_usd: 200
  max_open_prs_per_lane: 2
  max_issues_created_per_day: 5

circuit_breaker: { consecutive_failures: 3, same_pr_failures: 2 }

validation:                        # your commands; Laneguard is language-agnostic
  lint: "npm run lint"
  test: "npm test"
  build: "npm run build"

models:                            # tiers, not IDs. Reviewers default to a different model than the implementer
  observer: fastest
  triager: mid
  implementer: mid
  reviewer: strongest

extra_gates: []                    # additive only; the built-in gates cannot be removed
extra_protected_paths: []          # additive only
```

## Agents

Each lane run is orchestrated by the lane's main agent, which hands each step to a purpose-built subagent with only the inputs it needs.

| Agent | Phase | Access | Role |
|---|---|---|---|
| [`architect`](agents/architect.md) | design | docs write only | Approaches, `PRODUCT.md`, `ARCHITECTURE.md`, ADR drafts |
| [`planner`](agents/planner.md) | design | docs write only | Phased `WORKPLAN.md`, gates, testable acceptance criteria |
| [`observer`](agents/observer.md) | observe | read-only | Survey state; ranked candidate tasks; flags suspicious text |
| [`triager`](agents/triager.md) | diagnose | read-only | **Injection firewall:** untrusted issue to structured brief |
| [`gatekeeper`](agents/gatekeeper.md) | plan | read-only | Checks gates and protected paths; blocks when unsure |
| [`implementer`](agents/implementer.md) | implement | **only writer** | One major task, inside owned paths |
| [`validator`](agents/validator.md) | validate | read-only + configured commands | Runs lint/test/build once, reports faithfully |
| [`reviewer-dev`](agents/reviewer-dev.md) / [`-security`](agents/reviewer-security.md) / [`-design`](agents/reviewer-design.md) | review | read-only | Independent verdict against the approved acceptance criteria |

The `tools:` line in an agent file states intent. The enforced limit is the permission allowlist in `.claude/settings.json`, a protected path that `doctor` verifies.

## Security

Laneguard is a governance layer for agents that can change your repository. Read this section before you point it at anything real.

### Principles

1. **Prompts are not a security boundary.** Every guarantee below names the mechanism that enforces it outside the model.
2. **Least information, least privilege.** The agent that writes code never sees raw issue text. The identity it runs under cannot merge, deploy or change workflows.
3. **The agent cannot change its own rules.** Protocol, reviewer, limits, tool allowlist and engine version are owner-only.
4. **Fail closed.** If a gate is ambiguous, the run stops and asks a human.

### Trust boundaries

| Untrusted (treated as data, never as instructions) | Trusted |
|---|---|
| Issue, PR and comment text from anyone who is not an owner or triage-level collaborator | `owners:` approvals made as authenticated GitHub accounts |
| Fork contributions, web content, dependency contents, tool output | Files on protected paths, changed only by owner PRs |
| Anything a subagent returned (re-validated by the next step) | The pinned engine commit |

### Threat model

| Threat | Mitigation (where enforced) | Residual risk |
|---|---|---|
| **Prompt injection** through issues, PRs or comments | Triager firewall; implementer and reviewers never see raw text; acceptance criteria come only from the owner-approved plan; only owner-created or owner-labelled issues are acted on; corpus of injection tests | A model can still be fooled by content inside code or docs it legitimately reads. Review PRs from `propose` mode before trusting `autonomous` |
| **Lane edits its own protocol, reviewer, limits or allowlist** | Protected paths + CODEOWNERS + `check.py`; lanes run as a bot identity that is never an owner | An owner who merges a malicious PR defeats this |
| **Over-privileged token** | Dedicated GitHub App: no workflow-file write, no admin, no secrets access; owner token never used by a lane | Misconfiguration. `doctor` checks scopes |
| **Spoofed approval** | Approvals only via authenticated GitHub comments from listed owners, never edited after posting; email is notify-only, no inbound email handling | Compromise of an owner GitHub account |
| **Lock races, double runs, crashed runs** | Atomic compare-and-swap on a git ref via `lock.py`; one TTL; heartbeats; clock from the forge, never from model output | GitHub outage stalls lanes (fails safe: nothing runs) |
| **Runaway cost or infinite loops** | Per-run turn, token and minute caps; monthly ceiling; circuit breaker; PR and issue creation caps; cross-lane ping-pong rule; pause switch | Spend up to the configured ceiling is by design |
| **Weakening checks to "make it pass"** | `check.py` fails PRs that disable or loosen tests, lint, thresholds, branch protection or the checker | A subtle weakening the rules do not recognise; the independent reviewer is the second line |
| **Secret leakage** (commits, logs, reports) | Secret-pattern scanning in the checker; bot has no secrets access; reports and run history are scrubbed of environment values | Secrets pasted into code by a model in a form no pattern matches |
| **Malicious or surprise engine update** | Engine pinned to a full commit SHA; `migrate` only ever opens a PR for the owner | Trusting the engine's own source: audit it, it is small |
| **Dangerous dependency or network use** | Network and package-install commands absent from the implementer's allowlist unless the project adds them; reviewer flags new dependencies | Allowlist too permissive in your project |

### What is enforced, and by what

| Guarantee | Mechanism |
|---|---|
| No merge without an owner (`observe`, `propose`) | Branch protection: required PR, required CODEOWNERS review the bot cannot satisfy, bot not in the bypass list |
| No spending, cloud resources or deploys | The bot has no credentials for them; the tools are not in the allowlist |
| No contact with third parties or external publishing | Outbound tools and arbitrary egress denied; `gh` writes limited to this repo's issues, PRs, labels and comments |
| No force-push or history rewrite | Allowlist denies it (except `lock.py` on the lock ref); branch protection forbids it |
| Rules cannot be edited by a lane | Protected paths + CODEOWNERS + `check.py` |

### Recommended repository setup

1. **Create a dedicated GitHub App** for lanes. Grant only: contents (read and write), pull requests (read and write), issues (read and write), commit statuses (read and write; it posts the reviewer verdict). Step-by-step: [GitHub App setup](docs/setup/github-app.md). Do **not** grant: workflows, administration, secrets, environments, or organisation permissions. Never use a personal access token.
2. **Branch protection or a ruleset on your default branch:**
   - require a pull request and the `laneguard-guard` check (plus the reviewer check);
   - require CODEOWNERS review;
   - do **not** list the bot (or an admin you use for lanes) as a bypass actor;
   - block force-pushes and deletions.
3. **CODEOWNERS** for protected paths:
   ```text
   /.laneguard/              @your-login
   /.github/workflows/laneguard-*.yml   @your-login
   /.github/CODEOWNERS       @your-login
   /.claude/                 @your-login
   ```
4. **Actions hygiene:** pin third-party actions to full commit SHAs, set minimal `permissions:` per workflow, do not run lanes on `pull_request_target` from forks, and keep production and cloud secrets out of the lane's environment.
5. **Isolation:** run lanes on ephemeral runners or containers. Laneguard scopes permissions and tokens; it is **not a sandbox**.
6. **Start in `propose` mode** and read the PRs for a few weeks before allowing `autonomous`.

### What Laneguard does not protect against

- **Wrong or low-quality code.** Review and CI reduce this; nothing eliminates it.
- **A compromised owner account**, or an owner who approves a harmful change.
- **Sandbox escapes.** Run on isolated infrastructure if that matters to you.
- **Everything outside the repository** that the agent's environment can reach. Keep that environment small.
- **Model behaviour in general.** The design assumes models can be fooled and limits the damage rather than preventing the attempt.

The guard scripts and `doctor` now exist and have unit tests, but the guarantees have not been proven end to end against live GitHub, and no public conformance or injection results are published yet (see the [roadmap](#roadmap)). Treat this as a specification, a threat model and a tested set of guard scripts, not a finished product. The [security model](docs/security-model.md) maps each threat to its mechanism and test, and lists known limits.

### Reporting a vulnerability

Please report privately through the repository's **Security** tab ("Report a vulnerability"), not in a public issue. See [SECURITY.md](SECURITY.md).

## Documentation

- [Quickstart](docs/setup/quickstart.md): install, `init` flags, `doctor`, the adoption ladder, how to go back
- [GitHub App setup](docs/setup/github-app.md): the lane's bot identity, permissions and secrets
- [Branch protection](docs/setup/branch-protection.md): exact rules, protecting `laneguard-data`, what `doctor` verifies
- [Scheduler](docs/setup/scheduler.md): GitHub Actions cron, drift, concurrency and timeouts
- [Security model](docs/security-model.md): threats mapped to mechanisms and tests, and known limits
- [Design spec](docs/design-spec.md), [Changelog](CHANGELOG.md), [Contributing](CONTRIBUTING.md), [Security policy](SECURITY.md)
- [Launch drafts](docs/launch/README.md): drafts for the owner to review (not posted)

## How it compares

A survey of the Claude Code and agent ecosystem in October 2026 found these neighbours. Star counts are approximate and omitted; the point is what each is for.

| Project | What it is | How Laneguard differs |
|---|---|---|
| [spec-kit](https://github.com/github/spec-kit), [OpenSpec](https://github.com/Fission-AI/OpenSpec), [BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) | Spec-driven development workflows, mostly interactive | Laneguard includes a design pipeline too, but its focus is the unattended, scheduled phase and its enforcement |
| [superpowers](https://github.com/obra/superpowers) | A methodology of composable skills inside a session | Complementary: session-based methodology versus scheduled lanes with a control plane |
| [claude-code-action](https://github.com/anthropics/claude-code-action) | A GitHub Action that runs Claude Code on events | A building block. Laneguard can use it as the scheduler, and adds lanes, locks, gates and guardrails |
| OpenAI Symphony | A reference implementation that polls an issue tracker and dispatches agents | Symphony states it has no built-in sandboxing or approval gates; Laneguard's focus is exactly those |
| OpenHands, Copilot cloud agent, Devin | Full agent platforms | Larger scope, hosted or heavyweight. Laneguard is a small, auditable, repo-native control layer |

No surveyed project combined named scheduled lanes, a shared atomic lock and mechanically protected protocol files. That came from a limited search, not proof.

## Roadmap

**Done**
- [x] Design spec (draft v2) with threat model and enforcement table
- [x] Ten subagent definitions
- [x] Logo and brand assets
- [x] Plugin manifest and marketplace entry (installable preview)
- [x] Skills: `intake`, `spec`, `plan`, `core`, and the three lane skills
- [x] Commands: `new`, `run`, `status`, `pause`, `resume`, `init`, `doctor`, `migrate`, `eject`, wired to the scripts

**Next (in order)**
- [x] `lock.py` with concurrency tests (N racers, stale takeover, heartbeat)
- [x] `check.py` with protected-path, weakened-check and secret fixtures
- [x] `forge.py` (GitHub adapter, approval verification), `history.py`, `allowlist.py`
- [x] `init.sh` / `init.py`, the scaffold templates and `doctor.py` (scripts and unit tests)
- [x] `migrate.py`, `eject.py`, static dashboard, offline eval harness and injection corpus (mechanical tests only)
- [ ] Real (non-dry-run) lane runs, exercised end to end against live GitHub
- [ ] Live eval runs against fixture repos; publish results (none exist yet)
- [ ] Public example project with recorded runs


Open decisions (name checks, licence, default scheduler, reviewer model default) are tracked in [§16 of the spec](docs/design-spec.md).

## Repository layout

```text
.
├── README.md  SECURITY.md  LICENSE  CONTRIBUTING.md
├── .claude-plugin/   plugin.json  marketplace.json
├── assets/     logo-light.svg  logo-dark.svg  icon.svg
├── agents/     ten subagent definitions
├── skills/     intake  spec  plan  core  dev-lane  security-lane  design-lane
├── commands/   new  run  status  pause  resume  init  doctor  migrate  eject
└── docs/
    └── design-spec.md   the full design
```

Also present: `guard/` (engine scripts and tests), `scripts/` (init, migrate, eject), `dashboard/`, `templates/` (scaffold), `evals/` and `examples/`. The full target layout is in §3 of the spec.

## Contributing

The most useful contributions right now are on the design: threat-model review, attacks on the injection and lock designs, and edge cases the spec misses. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) © 2026 Werner Hurter
