## What and why

<!-- What changes, and the issue it addresses. -->

## Area

- [ ] guard scripts (`guard/`)
- [ ] scaffold / init (`scripts/`, `templates/`)
- [ ] commands / skills / agents
- [ ] docs
- [ ] evals
- [ ] CI / repo config

## Checklist

- [ ] All tests pass locally (see CONTRIBUTING.md for the three commands)
- [ ] **Guard changes** (`guard/`): new or updated tests, and I ran a mutation check (broke the new logic, confirmed a test fails, restored it)
- [ ] No docs claim a feature works that does not yet; no invented numbers or results
- [ ] A guarantee I added or changed names the mechanism that enforces it outside the model
- [ ] No secrets, tokens or private keys in the diff

## Protected paths and security impact

<!-- Does this touch guard scripts, workflows, the allowlist, config templates or agent files? Does it loosen any limit, gate or check? If yes, explain. -->
