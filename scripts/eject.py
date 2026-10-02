#!/usr/bin/env python3
"""eject.py: stop depending on the plugin by vendoring the engine's skills, agents and commands into
``.claude/`` of the project.

Honest scope: after eject, lanes run from files in your repo, not from a pinned plugin checkout.
``.laneguard/plugin.lock`` is kept, marked ``vendored: true``, and records which engine commit the
vendored files came from (provenance, and the checker still requires it to be a full SHA). Lane
workflows are regenerated without the engine checkout. Vendored commands are named
``/laneguard-<name>`` (plugin namespaces do not exist for project commands) and text references
``/laneguard:`` are rewritten to match. ``.claude/**`` is a protected path, so this is only ever an
owner-reviewed change (the /laneguard:eject command does the branch, commit and PR).

Usage: eject.py --engine-sha SHA [--target DIR] [--plugin-root DIR] [--apply] [--json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "guard"))
sys.path.insert(0, str(ROOT / "scripts"))
import init as ini  # noqa: E402
import laneconfig  # noqa: E402


def rewrite(text: str) -> str:
    return text.replace("/laneguard:", "/laneguard-")


def vendor_files(plugin_root: Path) -> dict:
    out = {}
    for d in ("skills", "agents"):
        for p in sorted((plugin_root / d).rglob("*")):
            if p.is_file():
                out[f".claude/{d}/{p.relative_to(plugin_root / d).as_posix()}"] = rewrite(p.read_text(encoding="utf-8"))
    for p in sorted((plugin_root / "commands").glob("*.md")):
        out[f".claude/commands/laneguard-{p.name}"] = rewrite(p.read_text(encoding="utf-8"))
    return out


def plan_eject(target: Path, plugin_root: Path, engine_sha: str) -> dict:
    if not laneconfig.is_full_sha(engine_sha):
        raise ini.InitError("--engine-sha must be the full 40-character commit SHA the files are vendored from")
    a = ini.args_from_project(target, engine_sha, vendored=True)
    plan = {rel: text for rel, text, _ in ini.build_plan(a, plugin_root)}
    writes = {rel: t for rel, t in plan.items() if rel.startswith(".github/workflows/laneguard-lane-") or rel == ".laneguard/plugin.lock"}
    vend = vendor_files(plugin_root)
    # settings.json must stay what allowlist would generate; do not vendor a settings file
    writes.update(vend)
    old = laneconfig.loads((target / ".laneguard/scaffold.version").read_text()) or {}
    files = dict(old.get("files") or {})
    for rel, text in writes.items():
        files[rel] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    ver = ini.engine_version(plugin_root)
    manifest = "\n".join([f"scaffold: {old.get('scaffold', ver)}", f"engine_version: {ver}", "vendored: true", "files:"]
                         + [f"  {k}: {v}" for k, v in sorted(files.items())]) + "\n"
    writes[".laneguard/scaffold.version"] = manifest
    return {"vendored_from": engine_sha, "files": sorted(writes), "_writes": writes}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="eject.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--engine-sha", required=True)
    ap.add_argument("--target", default=".")
    ap.add_argument("--plugin-root", default=str(ROOT))
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    try:
        plan = plan_eject(Path(a.target), Path(a.plugin_root), a.engine_sha)
        if a.apply:
            for rel, text in plan["_writes"].items():
                dest = Path(a.target) / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(text, encoding="utf-8")
    except (ini.InitError, laneconfig.YamlError, OSError) as e:
        print(f"eject error: {e}", file=sys.stderr)
        return 2
    print(json.dumps({"vendored_from": plan["vendored_from"], "applied": a.apply, "files": plan["files"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
