---
description: Remove the plugin dependency by vendoring the skills into the repo (not built yet in the 0.1 preview)
---

`/laneguard:eject` is planned but not built in this preview.

When built, it vendors the skills into `.claude/` and removes the engine pin, as an owner-reviewed PR. Vendoring writes to protected paths, so it can only ever be proposed to the owner, never applied by a lane.

Do not copy skills or agents into the repository or touch `.claude/`. Tell the owner this and stop.
