# Contributing to Laneguard

Laneguard is pre-alpha: the design is written, the implementation is not. That makes design feedback the most valuable contribution right now.

## Where help is most useful

1. **Attack the design.** Try to defeat a guarantee in the README "Security" section or in the [spec](docs/design-spec.md): the lock, the approval mechanism, protected paths, the triager firewall. Report real vulnerabilities privately (see [SECURITY.md](SECURITY.md)); post design critiques as issues.
2. **Spec gaps and contradictions.** Timings, paths and rules must agree everywhere. If they do not, open an issue naming the sections.
3. **Agent prompts.** The files in `agents/` are first drafts. Concrete failure cases (an input where an agent does the wrong thing) are more useful than rewrites.
4. **Injection corpus.** Malicious issues, PR descriptions and comments for the test suite.
5. **Implementation**, once the roadmap reaches it. Start with `lock.py` and `check.py`; both come with required tests.

## Ground rules

- Open an issue before a large change so the direction can be agreed.
- Guarantees must name the mechanism that enforces them. "The prompt tells the agent not to" is not an acceptable mitigation.
- Changes to anything that will become a protected path (`agents/`, the guard scripts, config templates, workflows) get extra scrutiny.
- Keep documentation honest: do not describe a feature as working before it is.

## Pull requests

Small, focused PRs with a clear description of what changes and why. Link the issue it addresses.
