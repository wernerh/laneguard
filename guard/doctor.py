#!/usr/bin/env python3
"""doctor.py: preflight that fails loudly when a guarantee is not actually enforced.

``/laneguard:doctor`` runs this. Lanes run it with ``--strict --as lane`` before any run in
``autonomous`` mode and refuse to continue unless it passes. Nothing is stored: there is no
"doctor passed" marker for a lane to forge, so the check is simply run again each time.

Checks:
  config, owners, engine pin, scaffold integrity (guard scripts match the recorded hashes),
  CODEOWNERS coverage of every protected path, the tool allowlist, workflows (pinned actions,
  no pull_request_target, lane wiring), model separation (implementer vs reviewer), reviewer
  agents, token identity and scope, branch protection / rulesets (pull request, CODEOWNERS
  review, required checks, no force-push, no app bypass).

Statuses: PASS, WARN (advisory), FAIL (a guarantee is not enforced), SKIP (could not be checked;
in --strict mode a skipped critical check counts as a failure).

Python 3, standard library only.

Usage:
  doctor.py [--root DIR] [--offline] [--strict] [--as auto|owner|lane] [--engine-root DIR] [--json]

Exit codes: 0 no failures; 1 one or more failures; 2 usage or environment error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import allowlist  # noqa: E402
import laneconfig  # noqa: E402

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"
GUARD_CHECK_CONTEXT = "laneguard-guard / check"
REVIEW_CONTEXT = "laneguard-review"
# The GitHub App id of GitHub Actions. A required check pinned to it can only be satisfied by a
# check run from Actions, never by a commit status that another app (such as the lane's own) posts.
GITHUB_ACTIONS_APP_ID = 15368
SAMPLE_PROTECTED = [
    ".laneguard/guard/check.py", ".laneguard/config.yaml", ".laneguard/plugin.lock",
    ".laneguard/scaffold.version", ".github/workflows/laneguard-guard.yml", ".github/CODEOWNERS",
    ".claude/settings.json",
]


@dataclass
class Check:
    id: str
    status: str
    detail: str
    critical: bool = True

    def to_dict(self):
        return {"id": self.id, "status": self.status, "detail": self.detail, "critical": self.critical}


# --------------------------------------------------------------------------- CODEOWNERS


def parse_codeowners(text: str) -> list:
    rules = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        rules.append((parts[0], parts[1:]))
    return rules


def codeowners_match(pattern: str, path: str) -> bool:
    anchored = pattern.startswith("/")
    pat = pattern.lstrip("/")
    is_dir = pat.endswith("/")
    if is_dir:
        pat = pat + "**"
    if not anchored and "/" not in pattern.rstrip("/"):
        pat = "**/" + pat
    return laneconfig.path_matches(pat, path)


def codeowners_for(rules: list, path: str) -> list:
    owners: list = []
    for pattern, who in rules:  # the last matching rule wins
        if codeowners_match(pattern, path):
            owners = who
    return owners


# --------------------------------------------------------------------------- rules analysis


def analyze_rules(rules: dict, cfg: dict) -> list:
    """Turn the forge's view of branch protection into checks."""
    eff = rules.get("effective_rules")
    classic = rules.get("classic_protection")
    rulesets = rules.get("rulesets")
    if eff is None and classic is None and rulesets is None:
        return [Check("branch-protection", SKIP,
                      "could not read branch protection or rulesets; run doctor as an owner with repository read access")]
    pr_required = code_owner = False
    approvals = 0
    contexts: set = set()
    # context -> integration/app id the check is pinned to (None when unpinned)
    check_apps: dict = {}
    force_blocked = deletion_blocked = False
    bypass_apps = False
    bypass_other = False
    bypass_unknown = False  # an active ruleset whose bypass_actors we could not see

    def note_check(context, app_id):
        if context is None:
            return
        contexts.add(context)
        # keep the pinned id if any source pins it
        check_apps[context] = check_apps.get(context) or app_id

    for rule in eff or []:
        t, p = rule.get("type"), rule.get("parameters") or {}
        if t == "pull_request":
            pr_required = True
            code_owner = code_owner or bool(p.get("require_code_owner_review"))
            approvals = max(approvals, int(p.get("required_approving_review_count") or 0))
        elif t == "required_status_checks":
            for c in p.get("required_status_checks", []):
                note_check(c.get("context"), c.get("integration_id"))
        elif t == "non_fast_forward":
            force_blocked = True
        elif t == "deletion":
            deletion_blocked = True
    if isinstance(classic, dict):
        rpr = classic.get("required_pull_request_reviews")
        if rpr:
            pr_required = True
            code_owner = code_owner or bool(rpr.get("require_code_owner_reviews"))
            approvals = max(approvals, int(rpr.get("required_approving_review_count") or 0))
            allow = rpr.get("bypass_pull_request_allowances") or {}
            if allow.get("apps"):
                bypass_apps = True
            if allow.get("users") or allow.get("teams"):
                bypass_other = True
        rsc = classic.get("required_status_checks") or {}
        for ctx in rsc.get("contexts") or []:
            note_check(ctx, None)
        for c in rsc.get("checks") or []:
            note_check(c.get("context"), c.get("app_id"))
        if (classic.get("allow_force_pushes") or {}).get("enabled") is False:
            force_blocked = True
        if (classic.get("allow_deletions") or {}).get("enabled") is False:
            deletion_blocked = True
    for rs in rulesets or []:
        if rs.get("enforcement") not in (None, "active"):
            continue
        if "bypass_actors" not in rs:
            # The rulesets *list* endpoint omits bypass_actors; only /rulesets/{id} returns them.
            # Without that data we cannot say "no bypass actors", so we must not report PASS.
            bypass_unknown = True
            continue
        for actor in rs.get("bypass_actors") or []:
            if actor.get("actor_type") == "Integration":
                bypass_apps = True
            else:
                bypass_other = True

    guard_required = GUARD_CHECK_CONTEXT in contexts
    guard_pinned = check_apps.get(GUARD_CHECK_CONTEXT) == GITHUB_ACTIONS_APP_ID
    if not guard_required:
        req_status, req_detail = FAIL, f"'{GUARD_CHECK_CONTEXT}' is not a required status check, so check.py can be skipped"
    elif not guard_pinned:
        req_status, req_detail = FAIL, (
            f"'{GUARD_CHECK_CONTEXT}' is required but not pinned to GitHub Actions (integration_id/app_id "
            f"{GITHUB_ACTIONS_APP_ID}), so a commit status with that context posted by any app, including the "
            f"lane's own, would satisfy it without check.py running")
    else:
        req_status, req_detail = PASS, f"'{GUARD_CHECK_CONTEXT}' is a required check pinned to GitHub Actions"

    autonomous = any(l.get("mode") == "autonomous" for l in cfg.get("lanes", {}).values())
    out = [
        Check("branch.pull-request", PASS if pr_required else FAIL,
              "a pull request is required before merging" if pr_required else
              "the default branch does not require pull requests, so a lane could push straight to it"),
        Check("branch.codeowner-review", PASS if code_owner and approvals >= 1 else FAIL,
              "CODEOWNERS review is required" if code_owner and approvals >= 1 else
              "CODEOWNERS review with at least one approval is not required, so protected paths are not owner-gated"),
        Check("branch.required-checks", req_status, req_detail),
        Check("branch.force-push", PASS if force_blocked else FAIL,
              "force-pushes are blocked" if force_blocked else "force-pushes to the default branch are not blocked"),
        Check("branch.deletion", PASS if deletion_blocked else WARN,
              "deleting the default branch is blocked" if deletion_blocked else "deleting the default branch is not blocked",
              critical=False),
    ]
    if autonomous:
        out.append(Check("branch.review-check", PASS if REVIEW_CONTEXT in contexts else FAIL,
                         f"'{REVIEW_CONTEXT}' is a required check" if REVIEW_CONTEXT in contexts else
                         f"a lane is in autonomous mode but '{REVIEW_CONTEXT}' is not a required status check, "
                         f"so it could merge without the independent review"))
    if bypass_apps:
        out.append(Check("branch.bypass", FAIL, "a GitHub App is allowed to bypass branch protection: the lane's bot must not be"))
    elif bypass_other:
        out.append(Check("branch.bypass", WARN, "bypass actors are configured; confirm the lane's bot identity is not among them",
                         critical=False))
    elif bypass_unknown:
        out.append(Check("branch.bypass", SKIP, "an active ruleset was listed without its bypass actors; "
                         "re-run with a token that can read /repos/{repo}/rulesets/{id} to verify no app can bypass"))
    else:
        out.append(Check("branch.bypass", PASS, "no bypass actors", critical=False))
    return out


# --------------------------------------------------------------------------- the doctor


class Doctor:
    def __init__(self, root=".", offline=False, strict=False, role="auto", engine_root=None, forge=None):
        self.root = Path(root)
        self.offline = offline
        self.strict = strict
        self.role = role
        self.engine_root = Path(engine_root) if engine_root else (
            Path(os.environ["CLAUDE_PLUGIN_ROOT"]) if os.environ.get("CLAUDE_PLUGIN_ROOT") else None)
        self.forge = forge
        self.cfg: Optional[dict] = None
        self.checks: list = []

    def add(self, *checks):
        for c in checks:
            if self.strict and c.status == SKIP and c.critical:
                c = Check(c.id, FAIL, f"{c.detail} (strict mode: a check that cannot run is a failure)", c.critical)
            self.checks.append(c)

    def read(self, rel: str) -> Optional[str]:
        p = self.root / rel
        return p.read_text(encoding="utf-8") if p.is_file() else None

    # ---- offline checks

    def check_config(self):
        text = self.read(laneconfig.CONFIG_PATH)
        if text is None:
            self.add(Check("config", FAIL, f"{laneconfig.CONFIG_PATH} not found; run /laneguard:init"))
            return False
        try:
            cfg = laneconfig._merge_defaults(laneconfig.loads(text))
        except laneconfig.YamlError as e:
            self.add(Check("config", FAIL, f"config.yaml does not parse: {e}"))
            return False
        problems = laneconfig.validate(cfg)
        if problems:
            self.add(Check("config", FAIL, "; ".join(problems)))
            return False
        self.cfg = cfg
        self.add(Check("config", PASS, f"valid ({len(cfg['lanes'])} lane(s), mode {cfg['mode']})"))
        return True

    def check_owners(self):
        owners = self.cfg["owners"]
        bots = [o for o in owners if str(o).endswith("[bot]")]
        if bots:
            self.add(Check("owners", FAIL, f"owners lists bot identities ({', '.join(bots)}); the bot must never be an owner"))
        else:
            self.add(Check("owners", PASS, f"{len(owners)} owner(s), {self.cfg['approvals_required']} approval(s) required"))

    def check_pin(self):
        text = self.read(".laneguard/plugin.lock")
        if text is None:
            self.add(Check("engine-pin", FAIL, ".laneguard/plugin.lock is missing"))
            return
        try:
            sha = str((laneconfig.loads(text) or {}).get("sha", ""))
        except laneconfig.YamlError as e:
            self.add(Check("engine-pin", FAIL, f"plugin.lock does not parse: {e}"))
            return
        if laneconfig.is_full_sha(sha):
            self.add(Check("engine-pin", PASS, f"pinned to {sha[:12]}"))
        else:
            self.add(Check("engine-pin", FAIL, "the engine pin is not a full 40-character commit SHA"))

    def check_scaffold(self):
        text = self.read(".laneguard/scaffold.version")
        if text is None:
            self.add(Check("scaffold", FAIL, ".laneguard/scaffold.version is missing, so guard scripts cannot be verified"))
            return
        try:
            meta = laneconfig.loads(text) or {}
        except laneconfig.YamlError as e:
            self.add(Check("scaffold", FAIL, f"scaffold.version does not parse: {e}"))
            return
        files = meta.get("files") or {}
        bad = []
        for rel, want in files.items():
            if not rel.startswith(".laneguard/guard/"):
                continue
            p = self.root / rel
            if not p.is_file():
                bad.append(f"{rel} is missing")
            elif hashlib.sha256(p.read_bytes()).hexdigest() != str(want):
                bad.append(f"{rel} differs from the recorded hash")
        guard_dir = self.root / ".laneguard" / "guard"
        if guard_dir.is_dir():
            for p in sorted(guard_dir.glob("*.py")):
                rel = p.relative_to(self.root).as_posix()
                if rel not in files:
                    bad.append(f"{rel} is not recorded in scaffold.version")
        guard_recorded = [r for r in files if r.startswith(".laneguard/guard/")]
        if not guard_recorded:
            bad.append("no guard scripts are recorded in scaffold.version")
        if bad:
            self.add(Check("scaffold", FAIL, "guard scripts do not match what init recorded: " + "; ".join(bad[:5])))
        else:
            self.add(Check("scaffold", PASS, f"scaffold {meta.get('scaffold', '?')}: {len(guard_recorded)} guard script(s) match recorded hashes"))

    def check_codeowners(self):
        text = self.read(".github/CODEOWNERS")
        if text is None:
            self.add(Check("codeowners", FAIL, ".github/CODEOWNERS is missing, so protected paths are not owner-gated"))
            return
        rules = parse_codeowners(text)
        owners = {o.lower() for o in self.cfg["owners"]}
        uncovered, team_only = [], []
        samples = list(SAMPLE_PROTECTED) + [p.replace("**", "x").replace("*", "x") for p in self.cfg.get("extra_protected_paths", [])]
        for path in samples:
            who = codeowners_for(rules, path)
            logins = {w.lstrip("@").lower() for w in who if "/" not in w}
            if logins & owners:
                continue
            (team_only if any('/' in w for w in who) else uncovered).append(path)
        if uncovered:
            self.add(Check("codeowners", FAIL, "no configured owner is CODEOWNER for: " + ", ".join(uncovered[:4])))
        elif team_only:
            self.add(Check("codeowners", WARN, "only team owners found for: " + ", ".join(team_only[:3]) +
                           "; doctor cannot confirm the team contains an owner", critical=False))
        else:
            self.add(Check("codeowners", PASS, f"all {len(samples)} protected path samples are owned by a configured owner"))

    def check_allowlist(self):
        text = self.read(allowlist.SETTINGS_PATH)
        if text is None:
            self.add(Check("allowlist", FAIL, f"{allowlist.SETTINGS_PATH} is missing; the tool allowlist is what limits agents"))
            return
        problems = allowlist.verify(self.cfg, text)
        if problems:
            self.add(Check("allowlist", FAIL, f"{len(problems)} difference(s) from the generated allowlist: " + "; ".join(problems[:3])))
        else:
            self.add(Check("allowlist", PASS, "matches the allowlist generated from config.yaml"))

    def check_workflows(self):
        wf_dir = self.root / ".github" / "workflows"
        guard = self.read(".github/workflows/laneguard-guard.yml")
        files = {"laneguard-guard.yml": guard}
        for lane in self.cfg["lanes"]:
            files[f"laneguard-lane-{lane}.yml"] = self.read(f".github/workflows/laneguard-lane-{lane}.yml")
        problems, notes = [], []
        for name, text in files.items():
            if text is None:
                problems.append(f"{name} is missing")
                continue
            if re.search(r"\bpull_request_target\b", text):
                problems.append(f"{name} uses pull_request_target (fork code could run with secrets)")
            for action, ref in re.findall(r"uses:\s*([^\s@]+)@([^\s#]+)", text):
                if action.startswith("./"):
                    continue
                if not laneconfig.is_full_sha(ref):
                    problems.append(f"{name}: {action}@{ref} is not pinned to a full commit SHA")
            if re.search(r"permissions:\s*write-all", text) or re.search(r"^\s*(workflows|administration|actions|secrets):\s*write", text, re.M):
                problems.append(f"{name} requests excessive workflow permissions")
            if not re.search(r"^\s*permissions:", text, re.M):
                problems.append(f"{name} does not set minimal permissions:")
            if re.search(r"^\s*contents:\s*write", text, re.M):
                notes.append(f"{name} grants contents: write to the workflow token")
        if guard and "check.py" not in guard:
            problems.append("laneguard-guard.yml does not run check.py")
        if guard:
            # The required-check context is the job's literal `name:`. If it drifts, the required check
            # becomes unsatisfiable (fail-closed, but every PR is stuck) and doctor's rules check would still PASS.
            names = re.findall(r"^\s+name:\s*['\"]?([^'\"\n]+?)['\"]?\s*$", guard, re.M)
            if GUARD_CHECK_CONTEXT not in [n.strip() for n in names]:
                problems.append(f"laneguard-guard.yml has no job named '{GUARD_CHECK_CONTEXT}', so the required check "
                                "of that name can never be satisfied")
        if guard and not re.search(r"\bpull_request\b", guard):
            problems.append("laneguard-guard.yml does not trigger on pull_request")
        run_max = self.cfg["limits"]["run_max_minutes"]
        max_turns = int((self.cfg["budgets"].get("per_run") or {}).get("max_turns", 0) or 0)
        for lane in self.cfg["lanes"]:
            text = files.get(f"laneguard-lane-{lane}.yml")
            if not text:
                continue
            if f"/laneguard:run {lane}" not in text and f"/laneguard-run {lane}" not in text:
                problems.append(f"laneguard-lane-{lane}.yml does not run '/laneguard:run {lane}'")
            if not re.search(r"cron:", text) and self.cfg["scheduler"].get("adapter") == "github-actions":
                problems.append(f"laneguard-lane-{lane}.yml has no schedule")
            m = re.search(r"timeout-minutes:\s*(\d+)", text)
            if not m:
                problems.append(f"laneguard-lane-{lane}.yml has no timeout-minutes")
            elif int(m.group(1)) != run_max:
                problems.append(f"laneguard-lane-{lane}.yml timeout-minutes is {m.group(1)}, config limits.run_max_minutes is {run_max}")
            # the turn budget is enforced by the workflow's --max-turns, so it must be the configured one
            m = re.search(r"--max-turns[\s=]+(\d+)", text)
            if not m:
                problems.append(f"laneguard-lane-{lane}.yml does not pass --max-turns")
            elif max_turns and int(m.group(1)) != max_turns:
                problems.append(f"laneguard-lane-{lane}.yml --max-turns is {m.group(1)}, config budgets.per_run.max_turns is {max_turns}")
            if "concurrency:" not in text:
                problems.append(f"laneguard-lane-{lane}.yml has no concurrency group")
        if problems:
            self.add(Check("workflows", FAIL, "; ".join(problems[:6]) + (f" (+{len(problems) - 6} more)" if len(problems) > 6 else "")))
        elif notes:
            self.add(Check("workflows", WARN, "; ".join(notes), critical=False))
        else:
            self.add(Check("workflows", PASS, f"{len(files)} Laneguard workflow(s): actions pinned to SHAs, minimal permissions, timeouts and turn budgets match config"))
        if self.cfg["scheduler"].get("adapter") != "github-actions":
            self.add(Check("scheduler", WARN, f"scheduler adapter is '{self.cfg['scheduler'].get('adapter')}'; "
                           "doctor can only verify GitHub Actions wiring, so check the schedule by hand", critical=False))

    def check_models(self):
        m = self.cfg["models"]
        warns = []
        for lane in self.cfg["lanes"]:
            rev = m.get(f"reviewer-{lane}")
            if rev is not None and rev == m.get("implementer"):
                warns.append(f"reviewer-{lane} and implementer both use tier '{rev}'")
        if warns:
            self.add(Check("model-separation", WARN, "; ".join(warns) + ": the reviewer should be a different model from the implementer", critical=False))
        else:
            self.add(Check("model-separation", PASS, "reviewers use a different tier from the implementer", critical=False))

    def check_reviewers(self):
        missing = []
        known = False
        for lane in self.cfg["lanes"]:
            name = f"reviewer-{lane}.md"
            have = (self.root / ".claude" / "agents" / name).is_file()
            if self.engine_root and (self.engine_root / "agents" / name).is_file():
                have = True
                known = True
            elif self.engine_root:
                known = True
            if not have:
                missing.append(lane)
        if not self.engine_root and missing:
            self.add(Check("reviewers", SKIP, "engine location unknown (set CLAUDE_PLUGIN_ROOT or pass --engine-root) and no project-level reviewer agents found", critical=False))
        elif missing:
            self.add(Check("reviewers", FAIL, "no reviewer agent for lane(s): " + ", ".join(missing) +
                           ". Every lane needs reviewer-<lane>; it may not be removed"))
        else:
            self.add(Check("reviewers", PASS, "every lane has a reviewer agent"))

    def check_validation(self):
        v = self.cfg.get("validation") or {}
        if not any(str(x).strip() for x in v.values()):
            self.add(Check("validation", WARN, "no validation commands are configured, so the validator has nothing to run", critical=False))
        else:
            self.add(Check("validation", PASS, "validation commands: " + ", ".join(k for k, x in v.items() if str(x).strip()), critical=False))

    def check_pause(self):
        d = self.root / ".laneguard"
        flags = sorted(p.name for p in d.glob("PAUSED*")) if d.is_dir() else []
        if flags:
            self.add(Check("pause", WARN, "paused: " + ", ".join(flags) + ". Lanes exit immediately until an owner removes the flag", critical=False))
        else:
            self.add(Check("pause", PASS, "no pause flags", critical=False))

    # ---- online checks

    def _forge(self):
        if self.forge is None:
            import forge as forge_mod
            self.forge = forge_mod.from_config(str(self.root))
        return self.forge

    def check_identity_and_rules(self):
        if self.offline:
            self.add(Check("token", SKIP, "offline: token identity and scope not checked"),
                     Check("branch-protection", SKIP, "offline: branch protection not checked"))
            return
        try:
            f = self._forge()
            login = f.whoami()
            rules = f.rules()
        except Exception as e:
            self.add(Check("token", SKIP, f"could not reach the forge: {str(e)[:160]}"),
                     Check("branch-protection", SKIP, "could not reach the forge"))
            return
        is_owner = bool(login) and f.is_owner(login)
        role = self.role if self.role != "auto" else ("owner" if is_owner else "lane")
        perms = rules.get("permissions") or {}
        if role == "lane":
            if is_owner:
                self.add(Check("token", FAIL, f"this run is using the owner's token ({login}); a lane must use its own bot identity"))
            elif perms.get("admin") or perms.get("maintain"):
                self.add(Check("token", FAIL, "the lane's token has admin or maintain rights; grant only contents, pull requests and issues (write)"))
            elif not perms:
                self.add(Check("token", SKIP, "could not read the token's repository permissions"))
            else:
                self.add(Check("token", PASS, f"lane identity {'(' + login + ') ' if login else ''}has no admin or maintain rights"))
        else:
            self.add(Check("token", SKIP, "running as an owner: re-run with the lane's bot token (--as lane) to verify its scope", critical=False))
        self.add(*analyze_rules(rules, self.cfg))

    def run(self) -> list:
        if not self.check_config():
            return self.checks
        self.check_owners()
        self.check_pin()
        self.check_scaffold()
        self.check_codeowners()
        self.check_allowlist()
        self.check_workflows()
        self.check_models()
        self.check_reviewers()
        self.check_validation()
        self.check_pause()
        self.check_identity_and_rules()
        return self.checks


def summarize(checks: list) -> tuple:
    fails = sum(1 for c in checks if c.status == FAIL)
    warns = sum(1 for c in checks if c.status == WARN)
    skips = sum(1 for c in checks if c.status == SKIP)
    return fails, warns, skips


def render(checks: list) -> str:
    lines = []
    for c in checks:
        lines.append(f"{c.status:5} {c.id:24} {c.detail}")
    fails, warns, skips = summarize(checks)
    lines.append("")
    lines.append(f"doctor: {'FAIL' if fails else 'PASS'} ({fails} failed, {warns} warnings, {skips} skipped)")
    return "\n".join(lines)


def main(argv=None, forge=None) -> int:
    ap = argparse.ArgumentParser(prog="doctor.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=".")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--strict", action="store_true", help="a critical check that cannot run counts as a failure")
    ap.add_argument("--as", dest="role", default="auto", choices=["auto", "owner", "lane"])
    ap.add_argument("--engine-root")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        checks = Doctor(args.root, args.offline, args.strict, args.role, args.engine_root, forge).run()
    except OSError as e:
        print(f"doctor error: {e}", file=sys.stderr)
        return 2
    fails, warns, skips = summarize(checks)
    if args.json:
        print(json.dumps({"passed": fails == 0, "failed": fails, "warnings": warns, "skipped": skips,
                          "checks": [c.to_dict() for c in checks]}, indent=2))
    else:
        print(render(checks))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
