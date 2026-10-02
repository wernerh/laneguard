# Contributing to Laneguard

Laneguard is pre-alpha: the design is written and the guard scripts, scaffold and tests exist, but lane runs have not been exercised end to end against live GitHub. Design feedback and attempts to break the guards are the most valuable contributions right now.

## Where help is most useful

1. **Attack the design.** Try to defeat a guarantee in the README "Security" section or in the [spec](docs/design-spec.md): the lock, the approval mechanism, protected paths, the triager firewall. Report real vulnerabilities privately (see [SECURITY.md](SECURITY.md)); post design critiques as issues.
2. **Spec gaps and contradictions.** Timings, paths and rules must agree everywhere. If they do not, open an issue naming the sections.
3. **Agent prompts.** The files in `agents/` are first drafts. Concrete failure cases (an input where an agent does the wrong thing) are more useful than rewrites.
4. **Injection corpus.** Malicious issues, PR descriptions and comments for the test suite.
5. **Implementation.** The guard scripts exist; see the roadmap in the README for what is next. Every guard change needs tests (see below).

## Ground rules

- Open an issue before a large change so the direction can be agreed.
- Guarantees must name the mechanism that enforces them. "The prompt tells the agent not to" is not an acceptable mitigation.
- Changes to anything that will become a protected path (`agents/`, the guard scripts, config templates, workflows) get extra scrutiny.
- Keep documentation honest: do not describe a feature as working before it is.

## Running the tests

Python 3.10 or newer, standard library only; no installation step. Run these from the repository root (CI runs the same commands on Python 3.10 to 3.13):

```bash
python3 -m unittest discover -s guard/tests       # lock, check, forge, history, allowlist, doctor, config
python3 -m unittest discover -s scripts/tests     # init / migrate / eject
python3 -m unittest discover -s dashboard/tests   # static dashboard
python3 -m unittest discover -s evals/tests -t .  # eval suite, offline (no network, no model calls)
python3 evals/conformance/check_agents.py         # static check of agents/*.md; exit 1 on problems
```

The guard tests create temporary git repositories, so `git` must be installed and able to commit (set `user.name` and `user.email` if it complains). Where the guard has a known limit that is a limit by design rather than a bug (for example, a paraphrased injection with no trigger phrase), the test asserts the current behaviour and says so in a comment, so the limit stays visible. When a gap is fixed, the test asserting it changes in the same PR.

## Rules for guard changes

Anything under `guard/` (and the templates and allowlist rules that depend on it) is what the safety claims rest on, so:

1. **A guard change needs a test.** A new rule, check or script option comes with a test that fails without it. A bug fix comes with a test that reproduces the bug.
2. **A guard change needs a mutation check.** Before opening the PR, break the new logic on purpose (invert the condition, delete the rule, loosen the threshold) and confirm at least one test fails; then restore it. Say in the PR that you did, and what you broke. A test that still passes against broken code is not protecting anything.
3. **Do not loosen a check to make a test pass.** Loosening a limit, gate or check needs an explicit justification in the PR description.
4. Standard library only. No new dependencies in `guard/` or `scripts/`.
5. Time comes from the forge, never the local clock (`lock.py` has a test that enforces this).

## Pull requests

Small, focused PRs with a clear description of what changes and why. Link the issue it addresses.
