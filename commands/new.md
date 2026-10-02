---
description: Design a project from an idea - intake, spec, plan - with owner approval at each stage
argument-hint: "<idea>"
---

Run the Laneguard design pipeline for this idea: $ARGUMENTS

If no idea was given, ask the owner for one sentence about what they want to build, then continue.

Work through the three stages in order, using the plugin's skills. Each stage ends with explicit owner approval, and you do not start the next stage without it:

1. Use the `intake` skill to produce an approved `docs/BRIEF.md`.
2. Use the `spec` skill to produce approved `PRODUCT.md`, `ARCHITECTURE.md` and ADRs.
3. Use the `plan` skill to produce an approved `docs/WORKPLAN.md` and `ROADMAP.md`, then open issues for Phase 1 only.

If a stage's output already exists and is approved, say so and ask whether to continue from the next stage or revise it. Do not overwrite an approved document without the owner saying so.

This command is interactive. If the owner is not present, stop and say it needs them.
