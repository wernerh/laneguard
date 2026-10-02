---
description: Pause all lanes, or one lane, by creating the pause flag
argument-hint: "[lane]"
---

Pause Laneguard. Argument (optional lane name): $ARGUMENTS

1. If a lane name is given, create `.laneguard/PAUSED.<lane>`. Otherwise create `.laneguard/PAUSED`. Create the `.laneguard/` directory if needed. Put the current reason and date in the file, taking the date from `date -u`, not from memory.
2. Do not commit or push. Tell the owner to commit the flag to the default branch for scheduled lanes to see it, and say that every lane run checks for it first.
3. Confirm which flag now exists.

Pausing is always safe and needs no approval. Removing a flag is a separate, owner-only action: see `/laneguard:resume`.
