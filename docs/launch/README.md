# Launch plan (drafts for the owner)

Everything in this directory is a **draft for the owner to review, edit and post by hand**. Nothing here has been posted, scheduled or sent. Claude did not and will not post any of it.

## Ground rules

1. **Be plain about the status.** Laneguard is pre-alpha. The guard scripts, scaffold and tests exist; lane runs have not been exercised end to end against live GitHub; no benchmarks, users, stars or results exist to cite. Every draft says so and none implies otherwise.
2. **No invented numbers, testimonials or comparisons.** Fill in a number only if you can link its source. Placeholders are marked `<<...>>`.
3. **Lead with the claim the design can support:** the limits live outside the prompt (protected paths, token scope, branch protection, an atomic lock, budgets). Do not lead with the spec-driven pipeline; others have that. See §15 of the [design spec](../design-spec.md).
4. **Do not buy, farm or trade stars.** It is detectable and damaging.
5. **Be honest about limits in every channel:** permission scoping is not a sandbox; the reviewer verdict is posted by the lane's own token, so independence is model and context separation, not identity. Linked from the [security model](../security-model.md#known-limits).
6. **Respect each community's self-promotion rules.** Read the current rules of Hacker News, r/ClaudeAI and any awesome list the day you post; they change.

## Do not launch until these are true

The spec's own launch plan puts proof before promotion. Suggested gates:

- [ ] [Name checks](naming-checks.md) are done and recorded.
- [ ] At least one real, recorded run against a throwaway GitHub repository: App created, branch protection set, `doctor` passing against live GitHub, one lane run in `propose` mode that opened a PR. Write down what broke. (Nothing in this repository has done this yet.)
- [ ] The required-check name (`laneguard-guard / check`) is confirmed against live GitHub, and any fix is released. See [branch protection](../setup/branch-protection.md#confirm-the-check-name).
- [ ] The README status block matches reality on launch day.
- [ ] `SECURITY.md` private reporting is enabled on the repository (Settings > Security > Private vulnerability reporting).
- [ ] You can respond to issues and comments for the first 48 hours.

If a gate is not met, launching as "a design and a set of guard scripts, looking for people to attack them" is still honest; the drafts are written to work for that framing. Adjust them if you have more to show.

## The drafts

| Draft | Channel |
|---|---|
| [show-hn.md](show-hn.md) | Hacker News "Show HN" title, URL and first comment |
| [x-thread.md](x-thread.md) | X (Twitter) thread |
| [reddit-claudeai.md](reddit-claudeai.md) | r/ClaudeAI post |
| [awesome-list-pr.md](awesome-list-pr.md) | Pull request text for a Claude Code awesome list (choose the list yourself) |
| [30-day-checklist.md](30-day-checklist.md) | Day-by-day checklist, adapted from the spec's launch plan |
| [naming-checks.md](naming-checks.md) | Name availability checks with commands, all unchecked |

## Shape of the launch

One 24 to 48 hour window for HN, X and Reddit, after the gates above. The ask in every post is the same and matches the project's real need: **try to break the guards, and review the threat model.** That is also the most honest thing to ask for at this stage.
