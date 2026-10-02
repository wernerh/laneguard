# X thread draft

Post by hand. Attach the demo video or GIF only if it exists and shows real behaviour (the spec's planned demo: an owner approves a plan, a lane picks up an issue, a gate stops an attempt to edit a protected file). If there is no real recording yet, post without media rather than mocking one up. Keep each post under the character limit when you edit.

1/
Scheduled coding agents are useful and risky in boring ways: runs collide, an agent edits its own rules, issue text steers it, "a human approves" is just a sentence in a prompt.

I'm building Laneguard, a Claude Code plugin that puts the limits outside the prompt. Pre-alpha, open source.

2/
The core claim: prompts are not a security boundary. Each guarantee should name what enforces it:

- protected paths: CODEOWNERS + branch protection + a CI checker
- bot identity: a GitHub App, never an owner, no workflow-write
- lock: a git ref, compare-and-swap pushes

3/
More of what's in the repo:

- budgets, a circuit breaker computed from run history, a monthly cost ceiling, a pause switch
- a read-only "triager" so the agent that writes code never sees raw issue text
- an adoption ladder: observe, then propose (PRs only), then autonomous

4/
Honest status: pre-alpha. The guard scripts and scaffold generator have unit tests that pass. I have NOT run it end to end against live GitHub for any length of time, and there are no benchmarks or results to show.

5/
Honest limits: permission scoping is not a sandbox. The reviewer's verdict is posted by the lane's own token, so its independence is a different model and fresh context, not a different identity. Full list in docs/security-model.md.

6/
What I want most: people trying to break it. A diff the checker should reject, a lock race, a path to a protected file, an injection that gets through. Private reports via the Security tab.

Repo: https://github.com/wernerh/laneguard
