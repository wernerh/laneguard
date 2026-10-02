# Security Policy

Laneguard is a governance layer for agents that can change a repository, so security reports are taken seriously.

## Project status

Laneguard is **pre-alpha**. The design and subagent definitions exist; the guard scripts and commands are not implemented yet. There are no supported releases. At this stage the most valuable reports concern the **design**: a way to defeat a stated guarantee, a flaw in the lock or approval model, or an injection route the threat model misses.

## Reporting a vulnerability

Please report privately. Do **not** open a public issue.

1. Go to this repository's **Security** tab.
2. Choose **Report a vulnerability** (GitHub private vulnerability reporting).

If that option is not visible, open a public issue titled "Security contact request" **without any details**, and a maintainer will arrange a private channel.

Please include:

- what the issue is and which guarantee or document it affects (for example a section of the spec or a file under `agents/`);
- steps or a minimal example to reproduce or demonstrate it;
- the impact you expect;
- any suggested fix.

Reports are handled on a best-effort basis by a single maintainer. You can expect an acknowledgement, a description of the planned response, and credit in the fix unless you prefer to stay anonymous. No response times are guaranteed at this stage.

## In scope

- Bypasses of a guarantee listed in the README "Security" section, including defeating a protected path, a human gate, the lock, the budget limits or the approval mechanism.
- Prompt-injection routes that cause a lane to act on untrusted text.
- Weaknesses in `lock.py`, `check.py`, `doctor`, the CI templates or the agent definitions, once they exist.
- Over-broad permissions requested by the GitHub App or the templates.
- Secret exposure through reports, run history or logs.

## Out of scope

- General model errors or low-quality code produced by a lane (use a normal issue).
- Compromise of an owner's GitHub account, or an owner approving a harmful change.
- Vulnerabilities in Claude Code, GitHub or other third-party software (report those to their vendors).
- Issues that require running with a configuration the documentation warns against (for example a bot identity listed as a bypass actor).
- Social engineering of maintainers, and denial of service by consuming a project's own configured budget.

## Disclosure

Please allow a reasonable period for a fix before publishing details. Good-faith research that avoids accessing other people's data and does not disrupt other users is welcome.
