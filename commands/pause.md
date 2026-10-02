---
description: Pause all lanes, or one lane
argument-hint: "[lane] [reason]"
---

Pause Laneguard. Arguments (optional lane, then reason): $ARGUMENTS

Run `python3 .laneguard/guard/history.py pause [--lane <lane>] --reason "<reason>" --by "<who>"`. This writes the flag (`PAUSED` for all lanes, `PAUSED.<lane>` for one) to the `laneguard-data` branch, which every lane run checks first through `history.py pause-check`. No commit to the default branch is needed.

If `history.py` cannot reach the remote, say so and do not claim the pause took effect. Confirm by running `history.py status --no-trip` and showing the paused state.

Pausing is always safe and needs no approval. Removing a flag is owner-only: see `/laneguard:resume`.
