---
name: intake
description: Stage 1 of the Laneguard design pipeline. Turns a rough idea into an owner-approved docs/BRIEF.md (purpose, users, constraints, success test). Use when running /laneguard:new or when the owner asks to start or revise a project brief.
---

# Intake: idea to brief

Stage 1 of 3 in the design pipeline (intake, spec, plan). The output is `docs/BRIEF.md`. Nothing is built at this stage and no code is written.

## Preconditions

- You are in the target repository.
- `.laneguard/config.yaml` may not exist yet (`/laneguard:init` is not built in the preview). If it is missing, take the owner's GitHub login from `gh api user --jq .login` and say which login you are treating as the owner.
- This stage is interactive. If you are running unattended (a scheduled run, no owner present), stop and report that intake needs the owner.

## Process

1. **Discover.** Ask the owner questions one at a time, most important first. Cover: the problem and who has it, what "done" looks like, hard constraints (stack, hosting, budget, compliance, deadlines), what is explicitly out of scope, and the riskiest unknown. Prefer multiple choice. Stop asking when you could write the brief without guessing.
2. **Write back.** Summarise your understanding in a few sentences and ask the owner to correct it. Repeat until they confirm.
3. **Write `docs/BRIEF.md`** with these sections, and nothing speculative:
   - Purpose (two or three sentences)
   - Users and their problem
   - Success test (observable, testable statements)
   - Constraints (stack, hosting, budget, legal, time)
   - Out of scope
   - Open questions (things the owner has not decided; do not fill them in)
4. **Request approval.** Present the brief and ask for explicit approval of the brief.

## Approval

Approval means an explicit `/approve brief` from a login listed in `owners:`. When `.laneguard/guard/forge.py` exists, verify it through that adapter. In the preview, where it does not exist, the owner confirming in this interactive session counts, and you record it at the end of the brief as `Approved by <login> on <date> (in-session, preview)`. Without approval, stop. Do not start the spec stage.

## Rules

- Record what the owner said, not what you assume. Unknowns stay in Open questions.
- Do not choose a stack, vendor or architecture here. That is the spec stage.
- Do not create issues, branches or PRs at this stage.
