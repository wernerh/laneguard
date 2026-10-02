---
description: Open a PR patching scaffold files to a newer engine version (not built yet in the 0.1 preview)
---

`/laneguard:migrate` is planned but not built in this preview. There is no scaffold version to migrate from yet.

When built, it opens a PR that patches scaffold files to a newer engine version, with a changelog. It touches protected paths, so it is never auto-merged and the owner always reviews it.

Do not edit `.laneguard/plugin.lock`, `.laneguard/scaffold.version` or any scaffold file. Tell the owner this and stop.
