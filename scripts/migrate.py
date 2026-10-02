#!/usr/bin/env python3
"""migrate.py: patch an initialised project's engine-managed files to a newer engine version.

It never touches files the project owns (CLAUDE.md, PROJECT_STATE.md, ROADMAP.md, WORKPLAN, config.yaml,
state, decisions, CODEOWNERS, lane notes, ci.yml). Engine-managed files are updated only if the project
has not edited them since init (hash in ``.laneguard/scaffold.version`` still matches); locally edited
files are reported as conflicts and left alone unless ``--overwrite-conflicts`` is given. A locally edited
guard script is always reported loudly: doctor will keep failing on it until an owner resolves it.

This writes to protected paths, so it only ever runs as an owner action and its result is a PR for owner
review (the /laneguard:migrate command does the branch, commit and PR). Never auto-merged.

Usage: migrate.py --engine-sha SHA [--target DIR] [--plugin-root DIR] [--apply] [--overwrite-conflicts] [--json]
Without --apply it is a dry run. Exit: 0 ok / nothing to do, 1 conflicts remain, 2 error.
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

MANAGED_PREFIXES = (".laneguard/guard/",)
MANAGED_EXACT = {
    ".laneguard/plugin.lock", ".claude/settings.json", "docs/DECISION-PROTOCOL.md", "docs/adr/ADR-TEMPLATE.md",
}
MANAGED_PATTERNS = (".github/workflows/laneguard-",)
ALWAYS_LAST = ".laneguard/scaffold.version"


def managed(rel: str) -> bool:
    return rel.startswith(MANAGED_PREFIXES) or rel in MANAGED_EXACT or rel.startswith(MANAGED_PATTERNS)


def h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_manifest(target: Path) -> dict:
    p = target / ".laneguard/scaffold.version"
    if not p.exists():
        raise ini.InitError(".laneguard/scaffold.version is missing; this project was not initialised by Laneguard")
    meta = laneconfig.loads(p.read_text()) or {}
    return meta, dict(meta.get("files") or {})


def plan_migration(target: Path, plugin_root: Path, engine_sha: str, overwrite_conflicts=False) -> dict:
    meta, recorded = read_manifest(target)
    vendored = bool((laneconfig.loads((target / ".laneguard/plugin.lock").read_text()) or {}).get("vendored")) \
        if (target / ".laneguard/plugin.lock").exists() else False
    a = ini.args_from_project(target, engine_sha, vendored=vendored)
    new_plan = {rel: text for rel, text, _ in ini.build_plan(a, plugin_root)}
    updates, adds, removes, conflicts, unchanged = [], [], [], [], []
    new_hashes = dict(recorded)
    for rel, text in new_plan.items():
        if rel == ALWAYS_LAST or not managed(rel):
            continue
        dest = target / rel
        nh = h(text)
        if not dest.exists():
            adds.append(rel)
            new_hashes[rel] = nh
            continue
        cur = h(dest.read_text(encoding="utf-8"))
        if cur == nh:
            unchanged.append(rel)
            new_hashes[rel] = nh
        elif rel in recorded and cur == recorded[rel]:
            updates.append(rel)
            new_hashes[rel] = nh
        elif overwrite_conflicts:
            updates.append(rel)
            new_hashes[rel] = nh
        else:
            conflicts.append(rel)  # keep the old recorded hash so doctor keeps flagging the edit
    for rel in sorted(recorded):
        if managed(rel) and rel not in new_plan and rel != ALWAYS_LAST:
            p = target / rel
            if p.exists() and h(p.read_text(encoding="utf-8")) == recorded[rel]:
                removes.append(rel)
                new_hashes.pop(rel, None)
            elif p.exists():
                conflicts.append(rel)
    new_ver = ini.engine_version(plugin_root)
    lines = [f"scaffold: {new_ver}", f"engine_version: {new_ver}", "files:"] + [f"  {k}: {v}" for k, v in sorted(new_hashes.items())]
    return {"from": str(meta.get("scaffold", "?")), "to": new_ver, "engine_sha": engine_sha,
            "updates": sorted(updates), "adds": sorted(adds), "removes": removes, "conflicts": sorted(conflicts),
            "unchanged": len(unchanged), "_texts": {r: new_plan[r] for r in updates + adds},
            "_manifest": "\n".join(lines) + "\n"}


def changelog(plan: dict) -> str:
    out = [f"# Laneguard migration {plan['from']} -> {plan['to']}", "",
           f"Pins the engine to `{plan['engine_sha']}`. Touches protected paths: owner review required, never auto-merge.", ""]
    for title, key in (("Updated", "updates"), ("Added", "adds"), ("Removed", "removes")):
        if plan[key]:
            out += [f"## {title}"] + [f"- `{r}`" for r in plan[key]] + [""]
    if plan["conflicts"]:
        out += ["## Not changed: edited locally since init (resolve by hand or re-run with --overwrite-conflicts)"]
        out += [f"- `{r}`" for r in plan["conflicts"]] + [""]
    out += ["Review the diff, then run `python3 .laneguard/guard/doctor.py` on the branch."]
    return "\n".join(out) + "\n"


def apply(plan: dict, target: Path) -> None:
    for rel, text in plan["_texts"].items():
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    for rel in plan["removes"]:
        (target / rel).unlink()
    (target / ".laneguard/scaffold.version").write_text(plan["_manifest"], encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="migrate.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--engine-sha", required=True)
    ap.add_argument("--target", default=".")
    ap.add_argument("--plugin-root", default=str(ROOT))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--overwrite-conflicts", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        plan = plan_migration(Path(a.target), Path(a.plugin_root), a.engine_sha, a.overwrite_conflicts)
        if a.apply:
            apply(plan, Path(a.target))
    except (ini.InitError, laneconfig.YamlError, OSError) as e:
        print(f"migrate error: {e}", file=sys.stderr)
        return 2
    public = {k: v for k, v in plan.items() if not k.startswith("_")}
    if a.json:
        print(json.dumps({**public, "applied": a.apply}, indent=2))
    else:
        print(changelog(plan))
    return 1 if plan["conflicts"] else 0


if __name__ == "__main__":
    sys.exit(main())
