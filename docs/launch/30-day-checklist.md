# 30-day checklist

Adapted from §15 of the [design spec](../design-spec.md#15-open-source-readiness-needed-to-earn-adoption-and-stars). It is a checklist for the owner, not a forecast. Tick items as you do them; none are done yet. Dates are relative (day 1 = the day you decide to start).

## Before day 1: gates

- [ ] [Name checks](naming-checks.md) done and recorded.
- [ ] One real recorded run on a throwaway repository (App, branch protection, `doctor`, a `propose` PR). Fix what breaks.
- [ ] Required-check name confirmed against live GitHub ([details](../setup/branch-protection.md#confirm-the-check-name)).
- [ ] Private vulnerability reporting enabled; repository topics set (`claude-code`, `claude-code-plugin`, `agents`, `ai-agents`, `autonomous-agents`).
- [ ] README status block, `docs/setup/*`, and `docs/security-model.md` re-read against reality.

## Days 1 to 7: proof and polish

- [ ] Record a short demo of something real (for example `doctor` output, a gate stopping a protected-path edit). No mock-ups.
- [ ] Run the eval suite and publish only the results you actually obtained, with how to reproduce. If there are none, say "no results yet".
- [ ] Publish a public example project only if it exists and has real recorded runs.
- [ ] Label a few good-first issues; make sure the issue templates and CI are working.

## Days 8 to 14: invite review

- [ ] Ask a small number of people you know (security-minded engineers, Claude Code users) to attack the design or try the quickstart. Ask for honest feedback, not endorsements.
- [ ] Fix what they find; note it in the changelog.

## Days 15 to 17: launch window (24 to 48 hours)

- [ ] Show HN ([draft](show-hn.md)); stay available to answer.
- [ ] X thread ([draft](x-thread.md)).
- [ ] r/ClaudeAI ([draft](reddit-claudeai.md)), following its self-promotion rules.
- [ ] Reply to every question and issue; label bugs; do not argue about the limits you have already documented.

## Days 18 to 30: follow through

- [ ] Open one awesome-list PR, if the list's rules fit a pre-alpha project ([draft](awesome-list-pr.md)).
- [ ] Optionally pitch one writer or newsletter with a short honest note; only if you have something real to show.
- [ ] Ship small fixes weekly and keep the changelog current.
- [ ] Triage issues within a day or two where you can; close what you will not do, with a reason.
- [ ] At day 30, write down what happened (real numbers only), what people found, and what you will do next. Decide whether to continue, narrow the scope, or stop.

## Never

- Buying, trading or farming stars, or fake accounts.
- Unbenchmarked productivity claims, invented testimonials, or implying lane runs worked in production when they have not.
