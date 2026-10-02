# Show HN draft

Review before posting. Check Hacker News's current Show HN guidelines first (a project people can try, no marketing language, no asking for upvotes). Post from your own account. Post the URL as the repository.


> **Edit before posting:** the status sentences say lane runs have not been run end to end against live GitHub, because that is true of this repository as of drafting. If you have since run them, say exactly what you ran and what happened, and nothing more.

## Title (pick one; keep it under 80 characters, no hype)

- `Show HN: Laneguard – guardrails for scheduled Claude Code agents (pre-alpha)`
- `Show HN: Laneguard – limits for unattended coding agents that live outside the prompt`

URL: `https://github.com/wernerh/laneguard`

## First comment (post immediately after submitting)

> Hi HN, I'm Werner. Laneguard is a Claude Code plugin I extracted from a private project where I let scheduled agents open pull requests. The thing that worried me wasn't the model writing bad code, it was everything around it: two runs colliding, an agent editing its own rules, issue text steering it, and "a human approves" being just a sentence in a prompt.
>
> So the idea is to enforce the limits outside the model:
>
> - protected paths (config, guard scripts, workflows, the tool allowlist, the engine pin) that only an owner can change, enforced by CODEOWNERS, branch protection and a CI checker that runs a copy taken from the base branch;
> - a bot identity (a GitHub App) with no admin and no workflow-write, which is never an owner or a bypass actor;
> - an atomic lock implemented as a git ref updated with compare-and-swap pushes, with leases and heartbeats, and time taken from GitHub's response header rather than anything a model wrote;
> - a run budget, a circuit breaker computed from run history, a cost ceiling and a pause switch;
> - an adoption ladder: observe, then propose (PRs only), then autonomous (merges its own PRs after required checks).
>
> Status, plainly: this is pre-alpha. The guard scripts, scaffold generator and their unit tests exist and pass. I have not yet run lanes end to end against live GitHub for any length of time, so I'm not claiming results, and there are no benchmarks. `doctor` checks that the repository settings it can read actually match the guarantees, but it is only as good as what the API shows it.
>
> Limits I want to be upfront about: permission scoping is not a sandbox (allowlisted commands still run real code with the job's secrets), and the reviewer's verdict is posted by the lane's own token, so its independence is a separate model and fresh context rather than a separate identity. Some budget caps are enforced by skills, not scripts. The full list is in docs/security-model.md.
>
> What I'd most like: people trying to break it. A diff the checker should reject and doesn't, a way to win the lock race, a path to a protected file, an injection that gets through. Private reports via the repo's Security tab; everything else as issues. Happy to answer questions about the design.

## Likely questions (answer honestly, from the repo)

- *"How is this different from claude-code-action / spec-kit / etc.?"* It can use claude-code-action as the scheduler. The difference it aims at is the enforcement layer; see the README's comparison table. Do not claim that nothing else does this; the README says that came from a limited search.
- *"Is it a sandbox?"* No. Say so first.
- *"Does it work?"* The unit tests pass; lane runs are not yet proven end to end. Say what you have actually run by the time you post.
- *"Why not just branch protection?"* Branch protection is required by Laneguard and `doctor` checks it. The rest (lock, protected-path logic, budgets, approval verification) is what branch protection does not give you.
