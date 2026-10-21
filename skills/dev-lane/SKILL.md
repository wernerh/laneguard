---
name: dev-lane
description: Parameters and objective for the Laneguard dev lane - one gated implementation task per run from the approved plan, reviewed by reviewer-dev. Use when running /laneguard:run dev or when a scheduled dev lane fires.
---

# Dev lane

Run the protocol in the `core` skill. This skill only supplies the lane parameters. If anything here conflicts with `core`, `core` wins.

| Parameter | Value |
|---|---|
| Lane name | `dev` |
| Label | `laneguard` (from `lanes.dev.label` in config) |
| Branch prefix | `laneguard/` |
| Owned paths | `PROJECT_STATE.md` (plus the repo source the plan assigns to the task) |
| Reviewer | `reviewer-dev` |
| Default schedule | every 2 hours |

## Objective

Move the approved plan forward by one major task per run: implement the next issue from the current phase of `docs/WORKPLAN.md`, to its acceptance criteria, in the smallest correct change.

## Priority order

1. Fix a red default branch or a failing required check that this lane's own work caused.
2. Finish this lane's own open PR if the reviewer asked for changes and the limit allows.
3. The next unclaimed issue in the **current** phase, in plan order, whose acceptance criteria exist.
4. Small, clearly related cleanups, up to two per run.

If nothing qualifies, the run is quiet: report that and stop.

## Lane-specific rules

- Work only on issues created by an owner or labelled by an owner, and whose acceptance criteria come from the approved `docs/WORKPLAN.md`.
- Never start work from a later phase until its phase gate is approved.
- Do not open more than `budgets.max_open_prs_per_lane` PRs. Do not create more than `budgets.max_issues_created_per_day` issues. Issues are opened by the orchestrator only (`forge.py write issue`); the implementer never opens one, it reports `NEEDS_ISSUE: <one line>` and the orchestrator decides.
- After the PR, update the next action in `PROJECT_STATE.md`.
