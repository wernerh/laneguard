#!/usr/bin/env python3
"""init.py: non-interactive Laneguard scaffold, used by /laneguard:init (via init.sh).

Renders ``templates/`` into a target repo, copies the guard scripts, pins the engine to a full
commit SHA, records a hash manifest in ``.laneguard/scaffold.version`` (so doctor can detect a
tampered guard script and migrate can detect local edits), and generates ``.claude/settings.json``
from the config. Always starts in ``mode: propose`` (lanes inherit the project mode). Existing files are
never overwritten unless ``--force`` is given, and a project that already has a ``scaffold.version`` is
refused without ``--force`` (use /laneguard:migrate instead). Python 3, standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "guard"))
import allowlist  # noqa: E402
import laneconfig  # noqa: E402

# Commit SHAs of the actions the templates use, looked up from the upstream tags named here.
ACTION_SHAS = {
    "CHECKOUT_SHA": "11bd71901bbe5b1630ceea73d27597364c9af683",       # actions/checkout v4.2.2
    "SETUP_NODE_SHA": "39370e3970a6d050c480ffad4ff0ed4d3fdee5af",     # actions/setup-node v4.1.0
    "SETUP_PYTHON_SHA": "0b93645e9fea7318ecaed2b359559ac225c90a2b",   # actions/setup-python v5.3.0
    "APP_TOKEN_SHA": "fee1f7d63c2ff003460e3d139729b119787bc349",      # actions/create-github-app-token v2.2.2
    "CLAUDE_ACTION_SHA": "97c53473391bff1901034d4b454b5bac7ab7a029",  # anthropics/claude-code-action v1
    # TODO: record the exact tag this SHA corresponds to
}
PLACEHOLDER = re.compile(r"(?<!\$)\{\{([A-Z][A-Z0-9_]*)\}\}")
REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
DEFAULT_MAX_TURNS = laneconfig.DEFAULT_BUDGETS["per_run"]["max_turns"]
# Dashboard files vendored into .laneguard/dashboard/ by eject (build.py finds ../guard from there).
DASHBOARD_FILES = ("build.py", "template.html")
GUARD_FILES = ("laneconfig.py", "lock.py", "forge.py", "forge_read.py", "check.py", "allowlist.py", "doctor.py", "history.py")
CI_TEMPLATES = {"generic": "ci.generic.yml.tmpl", "node": "ci.node.yml.tmpl", "python": "ci.python.yml.tmpl"}


class InitError(Exception):
    pass


def engine_version(root: Path) -> str:
    try:
        return json.loads((root / ".claude-plugin" / "plugin.json").read_text())["version"]
    except (OSError, ValueError, KeyError):
        return "0.0.0"


def cron_for(schedule: str, index: int) -> str:
    """Translate 'every 2h' / 'every 30m' / 'daily' to a cron expression, spreading start minutes by lane."""
    s = schedule.strip().lower()
    offset = (7 + 11 * index) % 60
    m = re.fullmatch(r"every\s+(\d+)\s*(m|min|minutes?|h|hours?)", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)[0]
        if unit == "m":
            if n < 5 or n > 59:
                raise InitError(f"schedule {schedule!r}: GitHub Actions needs 5 to 59 minutes")
            return f"{offset % n}-59/{n} * * * *" if n < 60 else f"{offset} * * * *"
        if n < 1 or n > 23:
            raise InitError(f"schedule {schedule!r}: hours must be 1 to 23")
        return f"{offset} */{n} * * *" if n > 1 else f"{offset} * * * *"
    if s in ("daily", "every day"):
        return f"{offset} 6 * * *"
    if s in ("weekly", "every week"):
        return f"{offset} 6 * * 1"
    raise InitError(f"schedule {schedule!r} is not understood; use 'every Nh', 'every Nm', 'daily' or 'weekly'")


def render(text: str, values: dict, where: str) -> str:
    def sub(m):
        if m.group(1) not in values:
            raise InitError(f"{where}: unknown placeholder {{{{{m.group(1)}}}}}")
        return str(values[m.group(1)])
    out = PLACEHOLDER.sub(sub, text)
    left = PLACEHOLDER.search(out)
    if left:
        raise InitError(f"{where}: unreplaced placeholder {left.group(0)}")
    return out


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def yq(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def heartbeat_for(lock_ttl: int) -> int:
    """Heartbeat interval that always satisfies validate(): at most half the lock TTL, never above 10."""
    return min(10, max(1, lock_ttl // 2))


def already_initialised(target: Path) -> bool:
    return (target / ".laneguard/scaffold.version").exists()


def args_from_project(target: Path, engine_sha: str, engine_repo=None, vendored=False, dashboard=None):
    """Rebuild init's inputs from an initialised project (used by migrate and eject)."""
    import types
    cfg = laneconfig._merge_defaults(laneconfig.load_file(target / laneconfig.CONFIG_PATH))
    lock = laneconfig.loads((target / ".laneguard/plugin.lock").read_text()) if (target / ".laneguard/plugin.lock").exists() else {}
    v = cfg.get("validation") or {}
    return types.SimpleNamespace(
        profile=cfg["profile"], project=cfg["project"], repo=cfg["repo"], owner=list(cfg["owners"]),
        approvals=cfg["approvals_required"], validation_lint=v.get("lint", ""), validation_test=v.get("test", ""),
        validation_build=v.get("build", ""), ci="none", engine_sha=engine_sha,
        engine_repo=engine_repo or lock.get("repo") or "wernerh/laneguard",
        run_max_minutes=cfg["limits"]["run_max_minutes"], max_turns=cfg["budgets"]["per_run"]["max_turns"],
        vendored=vendored,
        dashboard=(target / ".github/workflows/laneguard-dashboard.yml").exists() if dashboard is None else dashboard)


def build_plan(a, plugin_root: Path) -> list:
    """Return [(relative_path, text_or_bytes, kind)] for everything init will write."""
    lanes = laneconfig.PROFILE_LANES[a.profile]
    owners = a.owner
    if not owners:
        raise InitError("at least one --owner is required")
    if a.approvals > len(owners):
        raise InitError("--approvals cannot exceed the number of owners")
    if any(o.endswith("[bot]") for o in owners):
        raise InitError("a bot identity cannot be an owner")
    if not REPO_RE.fullmatch(a.repo):
        raise InitError("--repo must look like owner/name")
    # --engine-repo is interpolated unquoted into workflow YAML (`repository:`), so it gets the same shape check
    if not REPO_RE.fullmatch(a.engine_repo):
        raise InitError("--engine-repo must look like owner/name")
    if not laneconfig.is_full_sha(a.engine_sha):
        raise InitError("--engine-sha must be a full 40-character commit SHA")
    run_max = a.run_max_minutes
    if run_max < 1:
        raise InitError("--run-max-minutes must be at least 1")
    max_turns = int(getattr(a, "max_turns", DEFAULT_MAX_TURNS))
    if max_turns < 1:
        raise InitError("--max-turns must be at least 1")
    lock_ttl = run_max + 15
    lane_lines = []
    for i, lane in enumerate(lanes):
        d = laneconfig.DEFAULT_LANES[lane]
        owns = ", ".join(d["owns"])
        # no per-lane mode: lanes inherit the project mode so lowering it in config.yaml takes effect (issue #5)
        lane_lines.append(f'  {lane}: {{ label: {d["label"]}, schedule: {yq(d["schedule"])}, owns: [{owns}] }}')
    base = {
        # PROJECT is free text: PROJECT_YAML is the quoted form for config.yaml, PROJECT the bare form for Markdown
        "PROJECT": a.project, "PROJECT_YAML": yq(a.project), "REPO": a.repo, "PROFILE": a.profile,
        "OWNERS_YAML": "[" + ", ".join(owners) + "]",
        "OWNERS_LIST": ", ".join(owners),
        "OWNERS_CODEOWNERS": " ".join("@" + o for o in owners),
        "APPROVALS_REQUIRED": a.approvals,
        "LANES_YAML": "\n".join(lane_lines),
        "VALIDATION_LINT": a.validation_lint, "VALIDATION_TEST": a.validation_test, "VALIDATION_BUILD": a.validation_build,
        "VALIDATION_LINT_OR_TRUE": a.validation_lint or "true",
        "VALIDATION_TEST_OR_TRUE": a.validation_test or "true",
        "VALIDATION_BUILD_OR_TRUE": a.validation_build or "true",
        "RUN_MAX_MINUTES": run_max, "LOCK_TTL_MINUTES": lock_ttl, "HEARTBEAT_MINUTES": heartbeat_for(lock_ttl),
        "MAX_TURNS": max_turns,
        "ENGINE_VERSION": engine_version(plugin_root), "ENGINE_REPO": a.engine_repo,
        **ACTION_SHAS,
    }
    T = plugin_root / "templates"

    def tpl(rel, extra=None):
        p = T / rel
        if not p.is_file():
            raise InitError(f"template missing: {rel}")
        return render(p.read_text(encoding="utf-8"), {**base, **(extra or {})}, rel)

    plan = [
        ("CLAUDE.md", tpl("CLAUDE.md.tmpl"), "template"),
        ("PROJECT_STATE.md", tpl("PROJECT_STATE.md.tmpl"), "template"),
        ("ROADMAP.md", tpl("ROADMAP.md.tmpl"), "template"),
        ("docs/WORKPLAN.md", tpl("docs/WORKPLAN.md.tmpl"), "template"),
        ("docs/adr/ADR-TEMPLATE.md", tpl("docs/adr/ADR-TEMPLATE.md"), "template"),
        ("docs/DECISION-PROTOCOL.md", tpl("docs/DECISION-PROTOCOL.md.tmpl"), "template"),
        (".laneguard/config.yaml", tpl("laneguard/config.yaml.tmpl"), "template"),
        (".laneguard/state.yaml", tpl("laneguard/state.yaml.tmpl"), "template"),
        (".laneguard/decisions.yaml", tpl("laneguard/decisions.yaml.tmpl"), "template"),
        (".laneguard/plugin.lock", f"# Pinned engine commit. Change it only through a reviewed PR.\nrepo: {a.engine_repo}\nsha: {a.engine_sha}\n"
         + ("vendored: true\n" if getattr(a, "vendored", False) else ""), "generated"),
        (".github/CODEOWNERS", tpl("CODEOWNERS.tmpl"), "template"),
        (".github/workflows/laneguard-guard.yml", tpl("github/workflows/laneguard-guard.yml.tmpl"), "template"),
    ]
    for i, lane in enumerate(lanes):
        d = laneconfig.DEFAULT_LANES[lane]
        extra = {"LANE": lane, "LANE_LABEL": d["label"], "LANE_OWNS": ", ".join(d["owns"]),
                 "LANE_SCHEDULE": d["schedule"], "CRON": cron_for(d["schedule"], i)}
        plan.append((f".laneguard/lanes/lane-{lane}.md", tpl("lanes/lane.md.tmpl", extra), "template"))
        lane_tpl = "laneguard-lane.vendored.yml.tmpl" if getattr(a, "vendored", False) else "laneguard-lane.yml.tmpl"
        plan.append((f".github/workflows/laneguard-lane-{lane}.yml", tpl("github/workflows/" + lane_tpl, extra), "template"))
    if getattr(a, "dashboard", False):
        if getattr(a, "vendored", False):
            # after eject there is no engine checkout: the builder is vendored next to the guard scripts
            plan.append((".github/workflows/laneguard-dashboard.yml", tpl("github/workflows/laneguard-dashboard.vendored.yml.tmpl"), "template"))
            for name in DASHBOARD_FILES:
                src = plugin_root / "dashboard" / name
                if not src.is_file():
                    raise InitError(f"dashboard file missing in the engine: {name}")
                plan.append((f".laneguard/dashboard/{name}", src.read_text(encoding="utf-8"), "vendored"))
        else:
            plan.append((".github/workflows/laneguard-dashboard.yml", tpl("github/workflows/laneguard-dashboard.yml.tmpl"), "template"))
    if a.ci != "none":
        plan.append((".github/workflows/ci.yml", tpl("ci/" + CI_TEMPLATES[a.ci]), "template"))
    for name in GUARD_FILES:
        src = plugin_root / "guard" / name
        if not src.is_file():
            raise InitError(f"guard script missing in the engine: {name}")
        plan.append((f".laneguard/guard/{name}", src.read_text(encoding="utf-8"), "guard"))
    # settings generated from the config exactly as it will be written
    cfg = laneconfig._merge_defaults(laneconfig.loads(dict(plan_to_map(plan))[".laneguard/config.yaml"]))
    problems = laneconfig.validate(cfg)
    if problems:
        raise InitError("generated config is invalid: " + "; ".join(problems))
    plan.append((allowlist.SETTINGS_PATH, allowlist.render(allowlist.generate(cfg)), "generated"))
    manifest = {rel: sha256_text(text) for rel, text, _ in plan}
    lines = [f"scaffold: {engine_version(plugin_root)}", f"engine_version: {engine_version(plugin_root)}", "files:"]
    lines += [f"  {rel}: {h}" for rel, h in sorted(manifest.items())]
    plan.append((".laneguard/scaffold.version", "\n".join(lines) + "\n", "generated"))
    return plan


def plan_to_map(plan):
    return [(rel, text) for rel, text, _ in plan]


def apply_plan(plan: list, target: Path, force: bool) -> dict:
    written, skipped = [], []
    for rel, text, _kind in plan:
        dest = target / rel
        if dest.exists() and not force:
            skipped.append(rel)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        written.append(rel)
    return {"written": written, "skipped": skipped}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="init.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile", default="standard", choices=list(laneconfig.VALID_PROFILES))
    ap.add_argument("--project", required=True)
    ap.add_argument("--repo", required=True, help="owner/name of the target repository")
    ap.add_argument("--owner", action="append", default=[], help="owner GitHub login (repeatable or comma-separated)")
    ap.add_argument("--approvals", type=int, default=1)
    ap.add_argument("--validation-lint", default="")
    ap.add_argument("--validation-test", default="")
    ap.add_argument("--validation-build", default="")
    ap.add_argument("--ci", default="none", choices=["none", *CI_TEMPLATES])
    ap.add_argument("--engine-sha", required=True, help="full 40-character commit SHA of the engine to pin")
    ap.add_argument("--engine-repo", default="wernerh/laneguard")
    ap.add_argument("--dashboard", action="store_true", help="also add the optional dashboard workflow")
    ap.add_argument("--run-max-minutes", type=int, default=30)
    ap.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS,
                    help="per-run turn budget, written to config budgets.per_run.max_turns and the lane workflows' --max-turns")
    ap.add_argument("--plugin-root", default=str(ROOT))
    ap.add_argument("--target", default=".")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print what would be written")
    a = ap.parse_args(argv)
    a.vendored = False
    a.owner = [o.strip().lstrip("@") for chunk in a.owner for o in chunk.split(",") if o.strip()]
    try:
        if already_initialised(Path(a.target)) and not a.force:
            raise InitError("this project is already initialised (.laneguard/scaffold.version exists); "
                            "use /laneguard:migrate to update it, or --force to re-scaffold")
        plan = build_plan(a, Path(a.plugin_root))
        if a.dry_run:
            print(json.dumps({"would_write": [p for p, _, _ in plan]}, indent=2))
            return 0
        res = apply_plan(plan, Path(a.target), a.force)
    except (InitError, laneconfig.YamlError) as e:
        print(f"init error: {e}", file=sys.stderr)
        return 2
    print(json.dumps({"mode": "propose", "profile": a.profile, **res}, indent=2))
    if res["skipped"]:
        print(f"{len(res['skipped'])} existing file(s) left untouched; use --force to overwrite them", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
