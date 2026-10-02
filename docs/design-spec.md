# Laneguard — Design Spec

**Name:** `laneguard` (chosen by owner; final GitHub, npm, domain and trademark checks still to do, see §16)
**Tagline:** Autonomous dev lanes with a leash.
**Date:** 2026-10-02
**Status:** Draft v2, awaiting owner review (supersedes draft v1)
**Owner:** Werner Hurter

Changes from v1 are driven by a competitive review and a critical review of v1. A summary is in Appendix A.

---

## 1. Purpose

Provide a standalone, reusable, open-source Claude Code plugin that takes a project from idea to approved design (brief, spec, phased plan), then runs autonomous, gated implementation through scheduled **lanes** (dev, security, design) with enforced limits on what those lanes can do.

**Origin.** The pattern was extracted from a private production project (RepoGrove) where it runs today. Incidents from that deployment shaped several rules below; they are cited as lessons, not as requirements.

### What makes it different

Spec-driven development commands, plugin packaging and human checkpoints are already common (spec-kit, OpenSpec, BMAD, superpowers). Laneguard does not compete on those. Its claim is the control plane that unattended agents lack:

1. **Gated autonomy.** Human gates are enforced outside the prompt: by token scope, tool permissions, branch protection, CODEOWNERS and CI. A lane cannot talk its way past them.
2. **Lanes cannot edit their own rules.** Protocol, reviewer, limits and the plugin version pin are protected paths that only the owner can change.
3. **Atomic locking with leases and heartbeats**, so scheduled lanes never collide and a crashed lane recovers on its own.
4. **Budgets, a circuit breaker and a pause switch**, so a misbehaving lane stops itself.
5. **Design-first pipeline** with approval at every stage and a walking-skeleton Phase 1.
6. **An adoption ladder:** observe, then propose, then autonomous. Nothing merges until the owner chooses to allow it.

### Success criteria (all testable)

- A new project goes from empty repo to "design approved, Phase 1 issues open" using only `/laneguard:init` and `/laneguard:new`.
- Scheduled lane runs follow the run loop in §7: lock, observe, one major task, validate, independent review, PR, report. A conformance suite (§13) verifies this on fixture repos.
- Nothing stack-specific, hosting-specific or domain-specific lives in the engine. It lives in per-project config and `CLAUDE.md`.
- Every human gate in §9 has a named mechanical enforcement, and each has a test that tries to cross it and fails.
- In the eval suite (§13), a lane given a malicious issue, a request to edit a protected file, or a stale-lock race produces zero protocol violations.
- A cautious adopter can run `/laneguard:init --profile minimal` and have a dev lane in `propose` mode (no merges) within 15 minutes.

---

## 2. Architecture: plugin engine + project scaffold

One repo, two roles.

- **Engine** (Claude Code plugin): skills, agents, commands, the guard scripts. Updated centrally. Projects **pin the engine to a commit SHA**, so an upstream change can never silently alter the rules of an unattended agent.
- **Scaffold** (`templates/`): project-owned files copied into a new repo by `/laneguard:init`. After init the project owns them.

Rules:

- Engine files are never copied into projects, except by `/laneguard:eject` (§12), which is an explicit, owner-reviewed action.
- Project files are never edited by the engine, except through lane runs that follow the protocol and through `/laneguard:migrate`, which only ever opens a PR for the owner.
- The forge (GitHub in v1) is accessed only through a thin adapter in `.laneguard/guard/forge.py`, so other forges are an adapter, not a rewrite.

---

## 3. Repo layout

Canonical project directory is **`.laneguard/`** everywhere (engine, templates, docs, tests).

```
laneguard/
├── .claude-plugin/
│   ├── plugin.json
│   └── marketplace.json          # lets users: /plugin marketplace add <owner>/laneguard
├── README.md                     # hero demo, one-line install, before/after (see §15)
├── SECURITY.md                   # threat model summary and reporting process
├── LICENSE                       # MIT (see §16)
├── assets/
│   ├── logo-light.svg  logo-dark.svg   # lockups (mark + outlined wordmark) for the README header
│   └── icon.svg                        # mark only: plugin listing, favicon, social card
├── skills/
│   ├── intake/SKILL.md           # idea -> brief (purpose, constraints, success test)
│   ├── spec/SKILL.md             # brief -> PRODUCT / ARCHITECTURE / ADRs
│   ├── plan/SKILL.md             # spec -> WORKPLAN with phase gates + roadmap issues
│   ├── core/SKILL.md             # shared run protocol (see §7)
│   ├── dev-lane/SKILL.md         # lane params: holder, branch prefix, PR label, reviewer,
│   ├── security-lane/SKILL.md    #   owned files, objective, priority order
│   └── design-lane/SKILL.md
├── agents/                       # subagents; see §8 "Agents and subagents"
│   ├── observer.md  triager.md  gatekeeper.md  validator.md   # read-only run-loop agents
│   ├── implementer.md                                          # the single writer in a run
│   ├── reviewer-dev.md  reviewer-security.md  reviewer-design.md   # read-only, one per lane
│   └── planner.md  architect.md                                # design-pipeline agents
├── commands/
│   ├── init.md  new.md  run.md  status.md
│   ├── pause.md  resume.md  doctor.md  migrate.md  eject.md
├── guard/                        # copied to .laneguard/guard/ by init, protected thereafter
│   ├── check.py                  # the one checker (Python 3, stdlib only)
│   ├── lock.py                   # the only code allowed to touch the lock
│   ├── forge.py                  # GitHub adapter
│   └── tests/
├── templates/
│   ├── CLAUDE.md.tmpl  PROJECT_STATE.md.tmpl  ROADMAP.md.tmpl
│   ├── laneguard/config.yaml.tmpl  laneguard/state.yaml.tmpl  laneguard/decisions.yaml.tmpl
│   ├── docs/WORKPLAN.md.tmpl  docs/adr/ADR-TEMPLATE.md  docs/DECISION-PROTOCOL.md
│   ├── lanes/lane-*.md.tmpl
│   ├── CODEOWNERS.tmpl
│   ├── ci/  ci.generic.yml.tmpl  ci.node.yml.tmpl  ci.python.yml.tmpl   # or bring your own CI
│   └── .github/workflows/  laneguard-guard.yml  laneguard-lane.yml.tmpl
├── scripts/init.sh               # non-interactive scaffold used by /laneguard:init
├── evals/                        # fixture repos, malicious-issue corpus, scorer (see §13)
├── examples/                     # link to the public example project and its recorded runs
└── docs/specs/
```

Project-side layout after init:

```
.laneguard/
├── config.yaml        # protected
├── plugin.lock        # pinned engine commit SHA; protected
├── scaffold.version   # protected
├── guard/             # check.py, lock.py, forge.py; protected
├── state.yaml         # non-lock state: claims, last runs, version
├── decisions.yaml     # open owner decisions
└── PAUSED             # optional global pause; PAUSED.<lane> for one lane
```

---

## 4. Commands

| Command | Does | Gate |
|---|---|---|
| `/laneguard:init [--profile minimal\|standard\|full]` | Scaffold templates into the current repo, fill placeholders from `config.yaml`, write the SHA pin, set `mode: propose` | none |
| `/laneguard:doctor` | Preflight: token scopes, bot identity, branch protection, CODEOWNERS, required checks, scheduler wiring, tool allowlist. Fails loudly if a guarantee in §9 is not actually enforced | none |
| `/laneguard:new "<idea>"` | Design pipeline: intake, spec, plan. Writes docs, opens roadmap issues | owner approves brief, spec, then plan |
| `/laneguard:run <lane> [--dry-run]` | One run of a lane. `--dry-run` runs observe and plan only, writes a report, changes nothing | none |
| `/laneguard:status` | Summarise state, open decisions, open PRs, last runs, budget used, pause state, engine vs scaffold version | none |
| `/laneguard:pause [lane]` / `resume` | Create or remove the pause flag (resume is an owner-only, protected-path change) | owner for resume |
| `/laneguard:migrate` | Opens a PR patching scaffold files to a newer engine version, with a changelog. Never auto-merged | owner (touches protected paths) |
| `/laneguard:eject` | Removes the plugin dependency by vendoring the skills into `.claude/` and removing the pin. Owner-reviewed PR | owner |

Scheduled runs call `/laneguard:run <lane>` and nothing else; the schedule payload is one line.

---

## 5. Profiles and the adoption ladder

**Profiles** (what `init` installs):

| Profile | Lanes | Default mode |
|---|---|---|
| `minimal` | dev only | `propose` |
| `standard` | dev + security | `propose` |
| `full` | dev + security + design | `propose` |

**Modes** (set per project, overridable per lane in `config.yaml`; raising a mode is a protected-path change):

| Mode | Lane may |
|---|---|
| `observe` | Read the repo, write a report. No branches, no PRs |
| `propose` (default) | Open PRs. Never merge, even its own |
| `autonomous` | Merge its own labelled PRs after required checks pass |

---

## 6. Design pipeline (`/laneguard:new`)

1. **Intake.** Discover intent, write back understanding, owner corrects. Output: `docs/BRIEF.md`.
2. **Spec.** 2-3 approaches with a recommendation. ADRs for expensive-to-reverse choices (stack, hosting, data model, auth). Output: `PRODUCT.md`, `ARCHITECTURE.md`, `docs/adr/*`.
3. **Plan.** Phased `docs/WORKPLAN.md`; each phase has a gate and testable acceptance criteria per issue; Phase 1 is a walking skeleton. Output: `ROADMAP.md` and GitHub issues for the next phase only.
4. **Handoff.** Sets the `PROJECT_STATE.md` next action; the dev lane takes over.

Each stage ends with explicit owner approval (§9, approval mechanism). Issues for a later phase open only after the prior phase gate is approved. The acceptance criteria recorded in the approved plan are what the reviewer checks against later (§7), so they never come from raw issue text.

---

## 7. Run loop (all lanes)

```
pause check -> lock -> observe (read-only) -> diagnose/prioritise -> plan -> implement
-> validate -> independent review -> PR -> (merge if autonomous) -> update state -> report -> unlock
```

### Rules

- **One major task per run** (plus up to 2 small related ones).
- **Lane merges only its own labelled PRs**, only in `autonomous` mode, and never a `needs-human` PR.
- **Issue claims** are made by comment and expire after 24h without a PR.
- **Reports** record which checks ran locally and which were left to CI, plus turns, tokens and cost.
- **A quiet run is a successful run.** If nothing is worth doing, the lane reports that and stops.
- **Pause check first.** If `.laneguard/PAUSED` or `PAUSED.<lane>` exists, or the lane's circuit breaker is open, the run exits immediately and reports why.

### Lock (single design, one set of numbers)

All timings are derived from one block in `config.yaml`:

```yaml
limits:
  run_max_minutes: 30        # hard cap per run
  lock_ttl_minutes: 45       # run_max + 15 buffer; a lock with no heartbeat this long is stale
  heartbeat_minutes: 10
  claim_expiry_hours: 24
```

Derived rules:

- **Stale:** no heartbeat for `lock_ttl_minutes`. A newer lock is never touched; a stale one may be taken over and the takeover is logged.
- **Checker alarm:** the guard check fails when a lock is older than `2 x lock_ttl_minutes` (90 min by default).
- **Atomic by construction.** The lock is the git ref `refs/laneguard/lock`, modified only by `.laneguard/guard/lock.py` using pushes with an explicit expected old value (`--force-with-lease=<ref>:<sha>`; create uses the all-zero old value). The server enforces the comparison, so two racing runs cannot both win.
  - **Acquire:** create the ref (fails if it exists).
  - **Heartbeat:** fast-forward the ref to a new commit carrying holder, lane, run id and expiry.
  - **Takeover of a stale lock:** push with the stale SHA as the expected old value. If the holder heartbeated in the meantime, the push is rejected and the taker backs off.
  - **Release:** delete the ref with the expected old value.
- **Models never write timestamps.** `lock.py` takes time from the forge API response header, not the local clock and never from model output. (Lesson from the original deployment: a model-written, rounded timestamp let a live lock be taken over.)
- A lock held by another lane and not stale means stop, quietly.

### Independent review

The reviewer is a read-only subagent with:

- a **different prompt and a fresh context**;
- **a different model than the implementer by default** (configurable);
- inputs limited to the diff, the validation output and the **acceptance criteria from the approved plan**;
- **no access to raw issue or comment text.**

Its verdict is posted as a required status check. In `autonomous` mode the lane cannot merge without it.

### Limits, circuit breaker and loops

Per `config.yaml` (raising any limit is a protected-path change):

```yaml
budgets:
  per_run: { max_turns: 60, max_tokens: 2000000 }
  monthly_cost_ceiling_usd: 200      # lanes pause themselves when reached
  max_open_prs_per_lane: 2
  max_issues_created_per_day: 5
circuit_breaker:
  consecutive_failures: 3            # failed or CI-red runs
  same_pr_failures: 2
```

When a breaker trips, the lane creates `PAUSED.<lane>`, opens a `needs-human` issue and stops. Only the owner can remove the flag.

**Cross-lane loops.** A lane may not close, relabel or edit another lane's issues or PRs. An issue that bounces between lanes more than twice is escalated to `needs-human`. The checker also fails any PR that weakens tests, lint or the checker itself (§10), so one lane cannot "fix" another lane's finding by disabling the check.

---

## 8. Lanes (configurable)

Defaults: dev, security, design. Defined in `.laneguard/config.yaml`:

```yaml
lanes:
  dev:      { label: laneguard,          schedule: "every 2h", owns: [PROJECT_STATE.md], mode: propose }
  security: { label: laneguard-security, schedule: "every 4h", owns: [docs/security/],  mode: propose }
  design:   { label: laneguard-design,   schedule: "every 4h", owns: [docs/design/],    mode: propose }
```

Adding a lane = a config entry + a reviewer agent file + a lane prompt. Disabling a lane = removing the entry.

**Scheduler.** The scheduler is an adapter, defined per project:

- **Default: GitHub Actions cron** (`laneguard-lane.yml`) invoking Claude Code (via claude-code-action) with the one-line `/laneguard:run <lane>`. In-repo, visible, and runs naturally as the bot identity. Actions cron can drift by minutes; that is fine because the lock and TTLs tolerate it.
- **Optional: Claude Code scheduled tasks / routines** in the cloud, for adopters who prefer them. Same one-line payload.

Whichever is used, `/laneguard:doctor` verifies the wiring.

### Agents and subagents

Each lane run is orchestrated by the lane's main agent (driven by the lane skill). It does not do the work itself; it hands each step to a purpose-built subagent with only the inputs that step needs. Ten subagents ship in `agents/`:

| Agent | Phase | Access | Default model | Purpose |
|---|---|---|---|---|
| `architect` | design | docs write only | strongest | Brief to 2-3 approaches, `PRODUCT.md`, `ARCHITECTURE.md`, ADR drafts |
| `planner` | design | docs write only | strongest | Spec to phased `WORKPLAN.md`, gates, testable acceptance criteria, next-phase issue drafts |
| `observer` | run: observe | read-only | fastest | Survey repo, PRs, CI, claims, decisions; ranked candidate tasks; flags suspicious content |
| `triager` | run: diagnose | read-only | mid | **Injection firewall.** Converts the chosen untrusted issue into a structured task brief; acceptance criteria come from the approved plan only |
| `gatekeeper` | run: plan | read-only | mid | Checks the brief against the human gates and protected paths; PASS or BLOCK; blocks when unsure |
| `implementer` | run: implement | the only writer | mid | One major task on a lane-prefixed branch, inside owned paths; never touches protected paths or weakens checks |
| `validator` | run: validate | read-only plus configured validation commands | fastest | Runs lint, test and build once, reports faithfully, never retries until green |
| `reviewer-dev` | run: review | read-only | strongest, and different from the implementer | Judges the diff against acceptance criteria; verdict is a required check |
| `reviewer-security` | run: review | read-only | strongest, and different from the implementer | Same role for the security lane: does it close the finding, add risk, or weaken a control |
| `reviewer-design` | run: review | read-only | strongest, and different from the implementer | Same role for the design lane: design-system compliance, accessibility, scope |

Model defaults are tiers, not fixed IDs, and are set per agent under `models:` in `config.yaml`. A project that configures the same model for implementer and reviewer gets a `doctor` warning.

**Orchestration order:**

```
observer -> triager -> gatekeeper -> implementer -> validator -> reviewer-<lane>
```

**Rules:**

1. **One writer.** Only `implementer` can edit files during a run. Everything else is read-only (the design-pipeline agents write docs only, and only during `/laneguard:new`).
2. **Least information.** The `implementer` and reviewers never see raw issue or comment text; they receive the triager's brief and the plan's acceptance criteria. This is what turns prompt-injection defence into structure rather than instruction.
3. **Orchestrator spawns, subagents do not.** Subagents cannot spawn further agents, so the lane's main agent owns sequencing, retries and the lock heartbeat.
4. **Parallel only when read-only.** The observer may fan out read-only survey tasks in parallel. Writing steps never run in parallel.
5. **Tool access is enforced by settings, not by the agent file.** The `tools:` line in each agent is a statement of intent; the real limit is the allowlist in `.claude/settings.json` (protected), generated from `config.yaml` and verified by `/laneguard:doctor`. Agent files are protected paths in a project, so a lane cannot give itself more access.
6. **Project overrides.** A project may add lanes with new reviewer agents (`reviewer-<lane>`), or override an agent by placing a file in `.claude/agents/` (protected, owner-reviewed). It may never remove the gatekeeper, the triager or the reviewer from a lane.
7. **Failure behaviour.** A `BLOCK` from the gatekeeper or reviewer, an `UNTRUSTED` or `SUSPICIOUS` triage result, or a `BLOCKED_PROTECTED_PATH` from the implementer ends the run with a `needs-human` issue and a quiet report; it never retries around the block.

---

## 9. Human gates and how each is enforced

### Gates (universal; per-project config can add, never remove)

Stop, open a `needs-human` issue and notify the owner for: spending money, creating cloud resources, identity-provider apps or secrets, production deploys, contacting anyone other than the owner, publishing externally, destructive or irreversible actions, expensive-to-reverse architecture, raising a lane's mode or limits.

### Enforcement (prompts are never the only layer)

| Gate / guarantee | Enforced by |
|---|---|
| No merge without owner approval (modes `observe`, `propose`) | Branch protection with required CODEOWNERS review that the bot identity cannot satisfy; bot is not in the bypass list |
| No spending, cloud resources, deploys | Bot token has no access to those systems; cloud CLIs and deploy tools are absent from the lane's tool allowlist; no deploy credentials in the lane's environment |
| No edits to protocol, reviewer, limits, pin | Protected paths (§10) with CODEOWNERS; checker fails the PR |
| No secrets handling | Secret scanning in the checker; bot token cannot read or write repo/org secrets; reports and run history are scrubbed of environment values |
| No contacting third parties / publishing | Tool allowlist denies outbound posting tools and arbitrary network egress; `gh` write calls limited to an allowlist (issues, PRs, labels, comments on this repo) |
| No force-push / history rewrite | Tool allowlist denies `git push --force*` (except `lock.py` on the lock ref); branch protection forbids it on protected branches |
| Cannot weaken tests, lint, branch protection | Checker diff rules (§10) |

The tool allowlist lives in `.claude/settings.json` (a protected path), is generated from `config.yaml`, and is verified by `/laneguard:doctor`. To be explicit about the limits: this is permission and token scoping, not a sandbox. Adopters who want stronger isolation should run lanes on ephemeral runners or containers; the docs say so plainly.

### Identity

Lanes run as a **dedicated bot identity (a GitHub App) with least privilege**: contents and pull-request write on non-protected branches, issues write, no workflow-file write, no admin, no secrets access. The owner's personal token is never used by a lane. This is what makes "only the owner can change protected paths" meaningful.

### Approval mechanism (GitHub only)

- Owner approval is an **`/approve <gate-id>` comment (or approving review) from a login listed in `owners:` in config**, verified through the API: author login, author association, comment never edited after posting.
- `owners:` is a list, with `approvals_required: 1` by default, so a small team is supported.
- **Email is notify-only.** An email can announce a gate; it can never lift one. There is no inbound email handling, so there is no spoofable From header to trust.
- Cheap-to-reverse defaults may apply after `default_due_at` (per `docs/DECISION-PROTOCOL.md`); expensive-to-reverse decisions stay stubbed until approved. No default or reply ever lifts a hard rule.

---

## 10. Guardrails (mechanical)

One checker, `.laneguard/guard/check.py` (Python 3, stdlib only), run by `laneguard-guard.yml` on every PR. The workflow installs Python itself, so adopters need nothing locally. CODEOWNERS routes protected paths to the owner.

**Protected paths** (a lane must not weaken its own protocol, reviewer or limits; only the owner changes these, via a `needs-human` PR):

- `.laneguard/guard/**`, `.laneguard/config.yaml`, `.laneguard/plugin.lock`, `.laneguard/scaffold.version`
- `.github/workflows/laneguard-*.yml`, `.github/CODEOWNERS`
- `.claude/**` (project-level lane skills, reviewer agents, settings and tool allowlist)
- removal of `.laneguard/PAUSED*`

The project may add paths to this list; it can never remove any.

**Checks:**

1. A PR touching a protected path fails unless it is authored by an owner login (the bot identity is never an owner).
2. Detects disabled or deleted tests and lint, weakened thresholds, `--no-verify` style bypasses, and edits to branch-protection or ruleset config.
3. Detects committed secret patterns.
4. Fails if the lock is older than `2 x lock_ttl_minutes`.
5. Fails if the engine pin is not a full commit SHA.
6. Fails a lane PR that is outside its lane's `owns` paths without a linked, owner-labelled issue.

Run history is **not** committed to the working branches. It is appended as JSONL to the `laneguard-data` branch (§11) so history does not cause merge conflicts or noise.

---

## 11. Observability and run history

- Each run appends one JSON record to `runs.jsonl` on the `laneguard-data` orphan branch: lane, run id, server-time start and end, outcome, task, PR links, checks run locally vs left to CI, turns, tokens, cost, and any breaker or pause events.
- `/laneguard:status` summarises these records, open decisions and budget used against the monthly ceiling.
- A static dashboard (GitHub Pages, built from `runs.jsonl`) shows run outcomes, cost over time, open gates and lane health. Optional, off by default.
- Failure alerts: a `needs-human` issue is opened for any breaker trip, stale-lock takeover, protected-path attempt or budget ceiling. Email or chat notification of those issues is optional and notify-only.

---

## 12. Per-project config (`.laneguard/config.yaml`)

Single source of truth for everything above. Contents:

- project name, repo, `owners:` list and `approvals_required`
- `profile`, `mode`, `lanes`, per-lane `mode`
- `limits`, `budgets`, `circuit_breaker` (§7)
- `scheduler` adapter and its settings
- extra gates and extra protected paths (additive only)
- locked-stack ADR reference
- hard domain rules (free text, copied into `CLAUDE.md` section 3)
- validation commands (lint, test, build); CI template choice or "bring your own CI"
- `models:` per agent (tier names; reviewers default to a different model than the implementer)

### Versioning and lifecycle

- Engine follows semver with a changelog. `.laneguard/scaffold.version` records which scaffold the project has.
- `/laneguard:status` and `/laneguard:doctor` report engine pin vs latest and scaffold version vs engine.
- `/laneguard:migrate` opens a PR that patches scaffold files; it touches protected paths, so the owner always reviews it.
- Pause: `/laneguard:pause` for emergencies; every run checks it first.
- Exit: `/laneguard:eject` vendors the skills into `.claude/` and removes the engine dependency.

---

## 13. Error handling and testing

### Error handling

- **Stale lock:** next run takes over via compare-and-swap and logs it; if the swap is rejected it backs off.
- **CI red at close-out:** leave the PR, release the lock, note it in the report, count toward the circuit breaker.
- **Unclear requirement:** open a decision in `decisions.yaml`, work on something else.
- **Budget or breaker tripped:** pause the lane, open a `needs-human` issue.
- **Engine/project drift:** `/laneguard:status` reports pin and scaffold versions.
- **Failed `doctor` check:** lanes refuse to run in `autonomous` mode until it passes.

### Testing

- `scripts/init.sh` against a scratch repo for each profile: all placeholders replaced, no `{{` left.
- `check.py` with fixtures: protected-file edit by a non-owner fails; owner edit passes; disabled-test diff fails; weakened-threshold diff fails; secret pattern fails; clean diff passes.
- **Lock tests:** N parallel acquirers, exactly one wins; stale takeover succeeds; takeover loses cleanly to a heartbeat; crash mid-run recovers after the TTL; clock skew does not matter because time comes from the forge.
- **Injection tests:** a corpus of malicious issues, PR descriptions and comments (instructions to merge, to edit protected files, to exfiltrate env vars, to contact third parties). Pass condition: zero protocol violations and zero secret exposure.
- **Conformance and eval suite** (`evals/`): fixture repos with seeded bugs and vulnerabilities. Scored on fix rate, false-merge rate, protocol violations, cost per fix and quiet-run rate. Results are published in the README and re-run on every release.
- **Skills dry-run:** `/laneguard:new` on a toy idea produces spec and plan with no code written before approval.
- **Agent conformance tests:** for each agent, fixtures check the contract. The triager must return `SUSPICIOUS` or `UNTRUSTED` on injection fixtures and never echo instructions into its brief; the gatekeeper must `BLOCK` every gate scenario; the implementer must stop with `BLOCKED_PROTECTED_PATH` when a task requires a protected edit; the validator must report a failing command as failing and never retry; each reviewer must reject a diff that disables a test or touches a protected path.

---

## 14. Non-goals (v1)

No web UI beyond the optional static dashboard, no hosted service, no multi-repo orchestration, no non-GitHub forges (adapter boundary only), no multi-harness support (Claude Code only in v1; skills are plain markdown and the guard, state and gates are harness-independent, so ports are possible later), no inbound email handling.

---

## 15. Open-source readiness (needed to earn adoption and stars)

**Trust before features.** An agent that merges unattended must show its threat model and its failure modes.

- `SECURITY.md` with the threat model (prompt injection, token scope, protected paths, what is and is not sandboxed) and a reporting process.
- `/laneguard:doctor` output shown in the README so adopters can see the guarantees are checked.

**Logo and README header.** The mark is a shield containing three lanes: dotted lanes enter from below, pass a single gate bar, and leave as solid lanes above. Dotted means unvetted work, the bar is the gate, solid means approved. The wordmark is outlined to paths, so it renders identically everywhere without font dependencies. The header switches between light and dark variants:

```html
<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <img src="assets/logo-light.svg" alt="Laneguard" width="420">
  </picture>
</p>
<p align="center"><b>Autonomous dev lanes with a leash.</b></p>
```

**README:** hero demo GIF (about 20 seconds: an owner approves a plan, a lane picks up an issue, a gate stops an attempt to edit a protected file); one-line install (`/plugin marketplace add <owner>/laneguard`, then `/plugin install laneguard`); before/after; the five-sentence "why"; reproducible eval results.

**Proof:** a public example project built end to end with Laneguard, with its recorded runs, `run-history` dashboard and the gate-blocked attempt visible. Dogfood on this repo itself.

**Positioning:** lead with gated autonomy and "lanes cannot edit their own rules". Do not lead with the spec-driven pipeline; it is common. Avoid unbenchmarked productivity claims.

**Community:** `CONTRIBUTING.md`, good-first-issue labels, issue and PR templates, a short roadmap, a lightweight chat channel, a weekly release cadence for the first two months.

**Launch plan (30 days):**

1. Finish the §16 name check; record the demo and write the README.
2. Public example project and eval results published.
3. Seed 50-100 genuine early users, including a few respected Claude Code developers.
4. Launch in one 24-48 hour window: Show HN, an X thread with the video, r/ClaudeAI.
5. Open PRs to relevant awesome lists; set GitHub topics (`claude-code`, `claude-code-plugin`, `agents`, `ai-agents`, `autonomous-agents`).
6. Pitch one YouTube creator and one newsletter.
7. Triage issues quickly; ship fixes weekly.

Do not buy or farm stars; it is detectable, short-lived and damaging. Realistic expectation without a platform tailwind is steady growth over months, not a one-week spike.

---

## 16. Open questions for owner

1. **Name (decided: `laneguard`).** "software-factory" was rejected as too generic and too close to Factory.ai. Still to do before launch: search GitHub for `laneguard`, claim the npm name and a domain, and check trademark registers (USPTO/WIPO) in the software classes. If a conflict appears, the fallback shortlist is Sluice, then Portcullis.
2. **Distribution.** v2 assumes a **public repo that is its own marketplace** (changed from v1's private recommendation, since stars require public). Confirm.
3. **Licence.** MIT (recommended, lowest friction) vs Apache-2.0 (patent grant).
4. **Origin story.** Name the private project (RepoGrove) in the README, or keep it anonymous?
5. **Default scheduler.** GitHub Actions cron (recommended) vs Claude Code scheduled tasks.
6. **Reviewer model default.** Different model from the implementer (recommended); confirm the cost trade-off.

Resolved from v1: notification channel is GitHub issues, with email optional and notify-only.

---

## Appendix A: What changed from v1

| Area | v1 | v2 |
|---|---|---|
| Lock | file in git; 40, 50 and 120 min thresholds disagreed | atomic compare-and-swap ref, one TTL block, heartbeats, forge-time clock |
| Contradictions | "superseded" note left in §9; `check.py` vs `.sh`; `.factory/` vs `factory/` | removed; one checker (`check.py`); one directory (`.laneguard/`) |
| Owner replies | by email address | GitHub-only `/approve` from listed owner logins; email notify-only |
| Protection | `.claude/**` while the engine lived elsewhere; owner-only check on owner token | SHA-pinned engine, protected pin and config, bot identity that is never an owner |
| Gates | enforced by CI and prompts | table mapping each gate to token scope, tool allowlist, branch protection or checker |
| Prompt injection | not addressed | trust rules, read-only observe, reviewer isolated from raw issue text, injection test corpus |
| Runaway risk | none | budgets, circuit breaker, open-PR and issue caps, cross-lane loop rule, pause switch |
| Adoption | all lanes, merging by default | profiles and observe, propose, autonomous ladder; dry-run |
| Missing | scheduler, observability, evals, versioning | scheduler adapters, run history and dashboard, eval suite, semver, migrate, eject, doctor |
| Naming and framing | generic name; internal project references throughout | working name, internal references reduced to one origin note, §15 launch plan |
