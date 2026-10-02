---
description: Scaffold Laneguard into the current repo (not built yet in the 0.1 preview)
argument-hint: "[--profile minimal|standard|full]"
---

`/laneguard:init` is planned but not built in this preview. Arguments: $ARGUMENTS

Do not try to scaffold files by hand. The scaffold, guard scripts and templates it needs (`scripts/init.sh`, `templates/`, `guard/`) are not in the plugin yet.

Tell the owner:

- What works today: the ten subagents and the skills. `/laneguard:new` runs the design pipeline, `/laneguard:run <lane> --dry-run` rehearses a lane, and `/laneguard:status`, `/laneguard:pause` and `/laneguard:resume` work on whatever files exist.
- What `init` will do when built, from the design spec: copy the project scaffold into the repo, write `.laneguard/config.yaml` for the chosen profile (`minimal` is one dev lane; `standard` adds security; `full` adds design), pin the engine to a commit SHA, and set `mode: propose`.
- Where progress is tracked: the roadmap in the README.

Then stop.
