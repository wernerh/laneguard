#!/usr/bin/env python3
"""forge_read.py: the read-only face of forge.py, for agents that must never write.

The observer, triager and validator need the forge for one thing: reading. ``forge.py`` carries the
write commands too (claim, comment, PR, merge, review status), and the Claude Code allowlist in
``.claude/settings.json`` is project-wide, so it cannot grant ``forge.py read`` to one subagent and
``forge.py write`` to another. This wrapper is the answer: it exposes only the read commands, and the
Forge it drives has its write path disabled in code, so even a bug in this file cannot post anything.

The orchestrator keeps using ``forge.py``. Read-only agents are instructed to use only this script,
``evals/conformance/check_agents.py`` fails any read-only agent whose prompt mentions ``forge.py``,
and the allowlist grants this script separately so the two can be told apart in logs and hooks.

Python 3, standard library only.

Usage (identical to the read half of forge.py):
  forge_read.py now | whoami | permission LOGIN | trust --issue N
  forge_read.py approvals --target issue|pr --number N --gate GATE
  forge_read.py rules [--branch B]
  forge_read.py read issue N | pr N | comments N | issues [--label L] [--state S] | prs [...] | ci [--ref R] | claims [--lane L]
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import forge as forge_mod  # noqa: E402

READ_COMMANDS = ("now", "whoami", "permission", "trust", "approvals", "rules", "read")


class ReadOnlyForge(forge_mod.Forge):
    """A Forge whose write path is closed. Any attempt raises ForgeDenied before a request is made."""

    def _write(self, method: str, path: str, body: Optional[dict] = None):
        raise forge_mod.ForgeDenied(f"forge_read.py is read-only: refused {method} {path}")


def from_config(root: str = ".", transport=None) -> ReadOnlyForge:
    cfg = forge_mod.laneconfig.load_config(root=root)
    return ReadOnlyForge(cfg["repo"], cfg["owners"], cfg.get("approvals_required", 1), transport=transport,
                         claim_expiry_hours=cfg["limits"]["claim_expiry_hours"])


def main(argv=None, forge: Optional[forge_mod.Forge] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Reject the write command before argparse sees it, so the refusal is explicit and not a usage error.
    positional = [a for a in argv if not a.startswith("-")]
    if positional and positional[0] not in READ_COMMANDS:
        print(f"forge_read.py: '{positional[0]}' is not a read command (allowed: {', '.join(READ_COMMANDS)}). "
              "Only the orchestrator writes, through forge.py.", file=sys.stderr)
        return 2
    root = "."
    for i, a in enumerate(argv):
        if a == "--root" and i + 1 < len(argv):
            root = argv[i + 1]
        elif a.startswith("--root="):
            root = a.split("=", 1)[1]
    f = forge if forge is not None else from_config(root)
    if not isinstance(f, ReadOnlyForge):
        # A caller passed an ordinary Forge: wrap its transport in a read-only one rather than trust it.
        f = ReadOnlyForge(f.repo, f.owners, f.approvals_required, transport=f.t, claim_expiry_hours=f.claim_expiry_hours)
    return forge_mod.main(argv, forge=f)


if __name__ == "__main__":
    sys.exit(main())
