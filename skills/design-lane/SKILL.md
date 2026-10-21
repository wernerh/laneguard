---
name: design-lane
description: Parameters and objective for the Laneguard design lane - one gated design-docs or UI task per run, reviewed by reviewer-design. Use when running /laneguard:run design or when a scheduled design lane fires.
---

# Design lane

Run the protocol in the `core` skill. This skill only supplies the lane parameters. If anything here conflicts with `core`, `core` wins.

| Parameter | Value |
|---|---|
| Lane name | `design` |
| Label | `laneguard-design` (from `lanes.design.label` in config) |
| Branch prefix | `laneguard-design/` |
| Owned paths | `docs/design/` (plus the UI source a task names) |
| Reviewer | `reviewer-design` |
| Default schedule | every 4 hours |

## Objective

Keep the design system, design docs and UI consistent with the approved spec, one major task per run: tokens, components, documentation, accessibility fixes.

## Priority order

1. Accessibility defects with acceptance criteria in the approved plan.
2. Drift between the UI and the project's design system or tokens.
3. Missing or stale design documentation in `docs/design/`.
4. Design items from the current phase of `docs/WORKPLAN.md` that have acceptance criteria.

If nothing qualifies, the run is quiet: report that and stop.

## Lane-specific rules

- The project's design system and tokens are the source of truth. Do not invent new visual direction; if the task needs a decision about brand, palette or typography, that is an owner decision: the orchestrator opens a `needs-human` issue (the implementer never opens issues; it reports `NEEDS_ISSUE: <one line>`).
- Do not add third-party fonts, assets or services that carry licence or cost implications without an owner gate.
- Changes must keep accessibility requirements from the spec (contrast, keyboard use, labels). The reviewer checks these explicitly.
- Do not change application logic in a design task. If the design fix needs it, say so in the report.
