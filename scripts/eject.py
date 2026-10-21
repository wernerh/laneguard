#!/usr/bin/env python3
"""eject.py: stop depending on the plugin by vendoring the engine's skills, agents and commands into
``.claude/`` of the project.

Honest scope: after eject, lanes run from files in your repo, not from a pinned plugin checkout.
``.laneguard/plugin.lock`` is kept, marked ``vendored: true``, and records which engine commit the
vendored files came from (provenance, and the checker still requires it to be a full SHA). Lane
workflows are regenerated without the engine checkout. Vendored commands are named
``/laneguard-<name>`` (plugin namespaces do not exist for project commands) and text references
``/laneguard:`` are rewritten to match. The commands that only make sense with a plugin checkout
(``init``, ``migrate``, ``eject``) are not vendored; ``doctor`` is vendored without ``--engine-root``
(doctor then relies on the vendored ``.claude/agents/``). If the project has the optional dashboard
workflow, ``dashboard/build.py`` and its template are vendored into ``.laneguard/dashboard/`` and the
workflow is regenerated to use them. ``.claude/**`` is a protected path, so this is only ever an
owner-reviewed change (the /laneguard:eject command does the branch, commit and PR).

Usage: eject.py --engine-sha SHA [--target DIR] [--plugin-root DIR] [--apply] [--json]
Without --apply it is a dry run. Prints a changelog, or the plan as JSON with --json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "guard"))
sys.path.insert(0, str(ROOT / "scripts"))
import init as ini  # noqa: E402
import laneconfig  # noqa: E402

# Commands that need the plugin checkout (they run scripts/*.py from it) and so cannot work after eject.
NOT_VENDORED_COMMANDS = ("init.md", "migrate.md", "eject.md")
ENGINE_ROOT_ARG = re.compile(r'\s*--engine-root\s+"\$\{CLAUDE_PLUGIN_ROOT\}"')


def rewrite(text: str) -> str:
    return text.replace("/laneguard:", "/laneguard-")


def rewrite_command(name: str, text: str) -> str:
    text = rewrite(text)
    if name == "doctor.md":
        # no plugin checkout after eject: doctor finds reviewer agents in the vendored .claude/agents/
        text = ENGINE_ROOT_ARG.sub("", text)
    return text


def vendor_files(plugin_root: Path) -> dict:
    out = {}
    for d in ("skills", "agents"):
        for p in sorted((plugin_root / d).rglob("*")):
            if p.is_file():
                out[f".claude/{d}/{p.relative_to(plugin_root / d).as_posix()}"] = rewrite(p.read_text(encoding="utf-8"))
    for p in sorted((plugin_root / "commands").glob("*.md")):
        if p.name in NOT_VENDORED_COMMANDS:
            continue
        out[f".claude/commands/laneguard-{p.name}"] = rewrite_command(p.name, p.read_text(encoding="utf-8"))
    return out


def plan_eject(target: Path, plugin_root: Path, engine_sha: str) -> dict:
    if not laneconfig.is_full_sha(engine_sha):
        raise ini.InitError("--engine-sha must be the full 40-character commit SHA the files are vendored from")
    a = ini.args_from_project(target, engine_sha, vendored=True)
    plan = {rel: text for rel, text, _ in ini.build_plan(a, plugin_root)}
    writes = {rel: t for rel, t in plan.items()
              if rel.startswith((".github/workflows/laneguard-lane-", ".laneguard/dashboard/"))
              or rel in (".laneguard/plugin.lock", ".github/workflows/laneguard-dashboard.yml")}
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
    skipped = sorted(f"commands/{n}" for n in NOT_VENDORED_COMMANDS if (plugin_root / "commands" / n).is_file())
    return {"vendored_from": engine_sha, "files": sorted(writes), "not_vendored": skipped,
            "dashboard": a.dashboard, "_writes": writes}


def changelog(plan: dict) -> str:
    out = [f"# Laneguard eject (vendored from `{plan['vendored_from']}`)", "",
           "Touches protected paths (`.claude/**`, lane workflows): owner review required, never auto-merge.", "",
           "## Written"] + [f"- `{r}`" for r in plan["files"]] + [""]
    if plan["not_vendored"]:
        out += ["## Not vendored"]
        out += [f"- `{r}`: needs the plugin checkout (`${{CLAUDE_PLUGIN_ROOT}}/scripts/`), so it has no vendored equivalent"
                for r in plan["not_vendored"]]
        out += ["To change the scaffold after eject, edit the files by hand in an owner-reviewed PR, or re-run "
                "`eject.py` from a plugin checkout with the new engine SHA.", ""]
    out += ["## Notes",
            "- `/laneguard-doctor` no longer passes `--engine-root`: doctor reads reviewer agents from the vendored `.claude/agents/`."]
    if plan["dashboard"]:
        out += ["- The dashboard workflow builds from the vendored `.laneguard/dashboard/build.py` instead of the engine checkout."]
    out += ["", "Review the diff, then run `python3 .laneguard/guard/doctor.py --offline` on the branch."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="eject.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--engine-sha", required=True)
    ap.add_argument("--target", default=".")
    ap.add_argument("--plugin-root", default=str(ROOT))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json", action="store_true")
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
    if a.json:
        public = {k: v for k, v in plan.items() if not k.startswith("_")}
        print(json.dumps({**public, "applied": a.apply}, indent=2))
    else:
        print(changelog(plan))
    return 0


if __name__ == "__main__":
    sys.exit(main())
