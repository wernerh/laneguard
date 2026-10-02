---
description: Check that the guarantees are actually enforced (not built yet in the 0.1 preview)
---

`/laneguard:doctor` is planned but not built in this preview.

Do not claim any guarantee is verified. Without the guard scripts and scaffold there is nothing for `doctor` to verify, and a made-up pass would be worse than no check.

Tell the owner what `doctor` will check when built, from the design spec: token scopes and the bot identity, branch protection and required checks, CODEOWNERS, the tool allowlist in `.claude/settings.json`, scheduler wiring, and a warning when the implementer and reviewer use the same model. Lanes will refuse to run in `autonomous` mode until it passes.

If the owner wants to check one of these by hand today, offer to read the relevant settings with `gh` and report exactly what you see, labelled as a manual look and not as a `doctor` result.

Then stop.
