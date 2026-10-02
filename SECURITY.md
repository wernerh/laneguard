# Security Policy

Laneguard is a governance layer for agents that can change a repository, so security reports are taken seriously.

## Project status

Laneguard is **pre-alpha**. The design, subagent definitions, guard scripts and scaffold exist and have unit tests, but lane runs have not been exercised end to end against live GitHub, and there are no supported releases. The most valuable reports concern the **design and the guard scripts**: a way to defeat a stated guarantee, a flaw in the lock or approval model, or an injection route the threat model misses. The current model and its known limits are in [docs/security-model.md](docs/security-model.md).

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

## Scope notes

- The guarantees are the ones in the README "Security" section and [docs/security-model.md](docs/security-model.md). Limits listed there under "Known limits" (permission scoping is not a sandbox; the reviewer verdict is posted by the lane's own token, so its independence is model and context separation, not identity; heuristic detectors have documented misses) are known and documented. A report that shows one is worse than documented, or that finds an undocumented one, is welcome.
- Useful reports include a failing test, a diff that `check.py` should have rejected and did not, a way for a lane to reach a protected path, win a lock race or forge an approval, or a place where `doctor` reports PASS while a guarantee is not in place.
- Reports about the setup documents in `docs/setup/` (for example a permission that is broader than needed) are in scope.

## Out of scope

- General model errors or low-quality code produced by a lane (use a normal issue).
- Compromise of an owner's GitHub account, or an owner approving a harmful change.
- Vulnerabilities in Claude Code, GitHub or other third-party software (report those to their vendors).
- Issues that require running with a configuration the documentation warns against (for example a bot identity listed as a bypass actor).
- Social engineering of maintainers, and denial of service by consuming a project's own configured budget.

## Disclosure

Please allow a reasonable period for a fix before publishing details. Good-faith research that avoids accessing other people's data and does not disrupt other users is welcome.
