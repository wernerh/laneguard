# r/ClaudeAI draft

Check the subreddit's current rules and flair requirements (self-promotion and project posts often need specific flair or a weekly thread). Post from your own account, say you are the author in the post, and do not ask for upvotes.


> **Edit before posting:** the status sentences say lane runs have not been run end to end against live GitHub, because that is true of this repository as of drafting. If you have since run them, say exactly what you ran and what happened, and nothing more.

## Title

`I built a Claude Code plugin that enforces limits on scheduled agents outside the prompt (pre-alpha, looking for people to break it)`

## Body

I've been letting scheduled Claude Code agents open pull requests on a private project, and the risks that kept me up weren't about code quality: runs colliding, an agent editing its own rules, issue text steering it, and "a human approves" being a sentence in a prompt. I pulled the pattern out into an open-source plugin called **Laneguard**.

The idea is that every guarantee names the mechanism that enforces it, outside the model:

- **Protected paths** (config, guard scripts, workflows, tool allowlist, engine pin) changeable only by an owner, via CODEOWNERS, branch protection and a CI checker.
- **A bot identity** (a GitHub App) with no admin and no workflow write, never an owner or bypass actor.
- **An atomic lock** as a git ref with compare-and-swap pushes, leases and heartbeats.
- **Budgets, a circuit breaker, a cost ceiling and a pause switch.**
- **An adoption ladder**: `observe`, then `propose` (PRs only), then `autonomous`.
- `doctor` checks that the repo settings it can read match what the design assumes.

**Where it actually is:** pre-alpha. The guard scripts, scaffold and unit tests exist and pass. I haven't run lanes end to end against live GitHub for any real length of time, so I'm not claiming results or benchmarks. Some of the commands are still being wired up.

**Limits, upfront:** permission scoping is not a sandbox, and the reviewer verdict is posted by the lane's own token, so its independence is a separate model and context rather than identity. There's a "known limits" section in docs/security-model.md.

What I'm after is review: try to defeat a guarantee, find a way past the checker or the lock, or tell me what the threat model misses.

Repo: https://github.com/wernerh/laneguard
