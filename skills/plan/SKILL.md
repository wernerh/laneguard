---
name: plan
description: Stage 3 of the Laneguard design pipeline. Turns an approved spec into a phased docs/WORKPLAN.md with a gate per phase and testable acceptance criteria, then opens roadmap issues for the next phase only. Use after the spec is approved, via /laneguard:new.
---

# Plan: spec to phased work plan

Stage 3 of 3. Input: approved `PRODUCT.md`, `ARCHITECTURE.md` and ADRs. Output: `docs/WORKPLAN.md`, `ROADMAP.md`, and issues for the next phase only.

## Preconditions

- The spec carries a recorded owner approval. If not, stop and send the owner back to the spec stage.
- Interactive stage. If running unattended, stop and report that the plan needs the owner.

## Process

1. **Draft.** Delegate to the `planner` subagent with the approved spec as its input. It produces `docs/WORKPLAN.md`:
   - Phased. **Phase 1 is a walking skeleton**: the thinnest end-to-end slice that proves the architecture.
   - Each phase has a **gate**: a human-approved checkpoint before the next phase opens.
   - Each issue has **testable acceptance criteria**. These are what the reviewer agents check against later, so they must be specific and observable. They are never derived from raw issue text.
2. **Review.** Check that every acceptance criterion could be verified by someone who has only the diff and the test output. Rewrite vague ones ("works well", "is fast") into observable statements.
3. **Roadmap.** Write `ROADMAP.md` summarising phases and gates.
4. **Request approval** of the plan.
5. **Handoff, only after approval.**
   - Open GitHub issues for **Phase 1 only**, each with its acceptance criteria and the lane label from `.laneguard/config.yaml` (default `laneguard`). Show the owner the list of issues before creating them if the repo is unfamiliar to you. Issues for a later phase open only after the prior phase gate is approved.
   - Set the next action in `PROJECT_STATE.md` so the dev lane can take over.

## Approval

Explicit `/approve plan` from a login in `owners:`. Once the project is initialised, post the artifact on a tracking issue and verify with `python3 .laneguard/guard/forge.py approvals --target issue --number N --gate plan` (listed owner, real person, comment never edited). Before init there is no repository config or guard to verify against, so the owner confirming in this interactive session counts; record it at the end of `docs/WORKPLAN.md` as `Approved by <login> on <date> (in-session, unverified)`. Without approval, stop. Do not create issues.

## Rules

- Never open issues for more than the next phase.
- Never create issues, branches or PRs before the plan is approved.
- A plan that needs spending money, cloud resources or credentials marks that step as an owner gate in the workplan. It does not plan around the gate.
