---
name: spec
description: Stage 2 of the Laneguard design pipeline. Turns an approved docs/BRIEF.md into 2-3 candidate approaches with a recommendation, then PRODUCT.md, ARCHITECTURE.md and ADRs for expensive-to-reverse choices. Use after the brief is approved, via /laneguard:new.
---

# Spec: brief to product, architecture and ADRs

Stage 2 of 3. Input: an approved `docs/BRIEF.md`. Output: `PRODUCT.md`, `ARCHITECTURE.md`, and `docs/adr/*.md`. Docs only; no code.

## Preconditions

- `docs/BRIEF.md` exists and records owner approval. If not, stop and send the owner back to the intake stage.
- Interactive stage. If running unattended, stop and report that the spec needs the owner.

## Process

1. **Approaches.** Delegate to the `architect` subagent with the brief as its only input. It returns 2-3 candidate approaches with trade-offs and a recommendation. Present them to the owner, lead with the recommendation and say why, and ask which to take. Do not proceed on your own choice.
2. **Draft.** Once the owner picks, delegate to the `architect` again to draft:
   - `PRODUCT.md`: what is built, for whom, scope boundaries.
   - `ARCHITECTURE.md`: components, data flow, hosting, the locked stack.
   - `docs/adr/NNNN-<slug>.md`: one ADR for each expensive-to-reverse choice (stack, hosting, data model, auth, anything that costs money to undo). Use `docs/adr/ADR-TEMPLATE.md` if the project has one; otherwise use context, decision, consequences, alternatives considered.
3. **Review.** Read the drafts yourself against the brief. Flag any requirement the drafts drop, and anything they add that the brief did not ask for. Fix before presenting.
4. **Request approval** of the spec.

## Approval

Explicit `/approve spec` from a login in `owners:`. Once the project is initialised, post the artifact on a tracking issue and verify with `python3 .laneguard/guard/forge.py approvals --target issue --number N --gate spec` (listed owner, real person, comment never edited). Before init there is no repository config or guard to verify against, so the owner confirming in this interactive session counts; record it at the end of `ARCHITECTURE.md` as `Approved by <login> on <date> (in-session, unverified)`. Without approval, stop. Do not start the plan stage.

## Rules

- Expensive-to-reverse choices (stack, hosting, data model, auth, anything involving spending money or cloud resources) are always the owner's decision. Never settle them silently.
- The spec describes; it does not create accounts, cloud resources or issues.
- Keep ADRs short. One decision per ADR.
