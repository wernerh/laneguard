#!/usr/bin/env python3
"""check.py: the one Laneguard checker, run by laneguard-guard.yml on every pull request.

It judges a PR from its diff, using the configuration that exists on the BASE commit, so a PR can
never loosen the rules it is judged by. For the same reason the workflow runs a copy of this script
taken from the base branch, not from the PR.

Checks (spec section 10):
  1. protected paths: only an owner login may change them (the bot identity is never an owner);
     removal of a pause flag is protected, creation is not
  2. weakened checks: disabled or deleted tests and lint, lowered thresholds, bypass flags,
     removed CI steps, edits to branch-protection or ruleset config
  3. committed secret patterns (always an error, owners included; values are never printed)
  4. lock older than 2 x lock_ttl_minutes
  5. engine pin in .laneguard/plugin.lock is a full 40-hex commit SHA
  6. a lane PR outside its lane's ``owns`` paths needs a linked, trusted issue

Severity: findings on a non-owner PR are errors. Weakening findings on an owner PR are warnings
(an owner may legitimately change tests); secrets and structural problems are always errors.

Python 3, standard library only.

Usage:
  check.py --repo DIR --base SHA --head SHA --author LOGIN [--author-type User|Bot]
           [--labels a,b] [--linked-issues 1,2 | --pr-body-file F] [--offline] [--json]

Exit codes: 0 pass (warnings allowed); 1 one or more errors; 2 usage or environment error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import laneconfig  # noqa: E402

ERROR, WARNING = "error", "warning"

TEST_PATH_RES = [
    re.compile(p) for p in (
        r"(^|/)(tests?|__tests__|specs?)/", r"(^|/)test_[^/]+\.py$", r"_test\.(py|go|rs|rb|exs?)$",
        r"\.(test|spec)\.[cm]?[jt]sx?$", r"(Test|Tests|IT)\.(java|kt|cs)$",
    )
]
TEST_DEF_RE = re.compile(
    r"^\s*(?:async\s+def\s+test_|def\s+test_|func\s+Test|fn\s+test_|#\[test\]|@Test\b|@pytest\.mark\.parametrize"
    r"|(?:it|test|describe)(?:\.each)?\s*\(|\[Fact\]|\[Theory\])"
)
SKIP_MARKERS = [
    (re.compile(r"@pytest\.mark\.(skip|skipif|xfail)\b|pytest\.(skip|xfail|importorskip)\("), "pytest skip/xfail"),
    (re.compile(r"@unittest\.(skip|skipIf|skipUnless|expectedFailure)\b|\bself\.skipTest\("), "unittest skip"),
    (re.compile(r"\b(it|test|describe)\.(skip|todo)\s*\(|\bx(it|describe|test)\s*\(|\b(it|test|describe)\.only\s*\("),
     "JS/TS test skip or .only"),
    (re.compile(r"\bt\.Skip(Now)?\("), "Go t.Skip"),
    (re.compile(r"#\[ignore\]|@Ignore\b|@Disabled\b"), "ignored test"),
]
BYPASS_MARKERS = [
    (re.compile(r"--no-verify\b"), "--no-verify bypass"),
    (re.compile(r"\bHUSKY\s*=\s*0\b|\bSKIP_(HOOKS|CHECKS|TESTS|LINT)\b"), "hook/check bypass variable"),
    (re.compile(r"\[skip ci\]|\[ci skip\]"), "CI skip marker"),
]
CI_FILE_RE = re.compile(r"^\.github/workflows/.*\.ya?ml$|^\.gitlab-ci\.yml$|(^|/)(package\.json|Makefile|tox\.ini|noxfile\.py)$")
WORKFLOW_RE = re.compile(r"^\.github/workflows/.*\.ya?ml$")
CHECK_CMD_RE = re.compile(
    r"(npm|yarn|pnpm)\s+(run\s+)?(test|lint|typecheck)|\bpytest\b|\bgo\s+test\b|\bcargo\s+(test|clippy)\b|\beslint\b"
    r"|\bruff\b|\bflake8\b|\bmypy\b|\btsc\b|\bjest\b|\bvitest\b|\bunittest\b"
)
BLANKET_LINT_RE = re.compile(
    r"/\*\s*eslint-disable\s*\*/|//\s*eslint-disable\s*$|#\s*flake8:\s*noqa\s*$|#\s*pylint:\s*skip-file|//\s*@ts-nocheck|#\s*mypy:\s*ignore-errors"
)
PROTECTION_CONFIG_RES = [
    re.compile(p) for p in (
        r"^\.github/rulesets/", r"^\.github/settings\.ya?ml$", r"^\.github/branch[-_]protection", r"branch[-_]protection[^/]*\.(json|ya?ml)$",
        r"^\.github/repository[^/]*\.ya?ml$",
    )
]
# lower bound: lowering it weakens the check. upper bound: raising it weakens the check.
LOWER_KEYS = re.compile(r"(fail[_-]under|cov[-_]fail[-_]under|minimum[_-]coverage|min[_-]coverage|coverage[_-]?threshold)\W{0,4}\s*[:=]?\s*[\"']?(\d+(?:\.\d+)?)")
LOWER_NESTED = re.compile(r"\b(statements|branches|functions|lines)\b\W{0,3}\s*[:=]\s*(\d+(?:\.\d+)?)")
UPPER_KEYS = re.compile(r"(max[_-]warnings|maxWarnings|max[_-]complexity|max[_-]line[_-]length|max[_-]lines)\W{0,4}\s*[:=]?\s*[\"']?(\d+)")

PLACEHOLDER_RE = re.compile(r"(?i)(example|placeholder|changeme|change-me|your[-_ ]|<[^>]+>|\$\{|\{\{|xxxx|\*{4,})")
SECRET_PATTERNS = [
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{50,}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("Stripe live key", re.compile(r"\b[sr]k_live_[A-Za-z0-9]{16,}\b")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("OpenAI-style API key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP |ENCRYPTED )?PRIVATE KEY-----")),
    ("JSON web token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
]
GENERIC_SECRET_RE = re.compile(
    r"""(?ix)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|private[_-]?key)\w*\s*[:=]\s*["']([^"'\s]{12,})["']""")


@dataclass
class Finding:
    check: str
    severity: str
    message: str
    path: str = ""
    line: int = 0

    def to_dict(self):
        return {"check": self.check, "severity": self.severity, "message": self.message,
                "path": self.path, "line": self.line}


@dataclass
class Change:
    path: str
    status: str  # A, M, D
    added: list = field(default_factory=list)    # (lineno, text)
    removed: list = field(default_factory=list)  # (lineno, text)


@dataclass
class Context:
    cfg: Optional[dict]                   # config from the base commit (None: bootstrap)
    author: str
    author_type: str = "User"
    labels: tuple = ()
    linked_issues: tuple = ()
    read_head: Callable[[str], Optional[str]] = lambda p: None
    read_base: Callable[[str], Optional[str]] = lambda p: None
    trust_issue: Optional[Callable[[int], dict]] = None
    lock_status: Optional[Callable[[], dict]] = None

    @property
    def author_is_owner(self) -> bool:
        if not self.cfg or self.author_type == "Bot" or self.author.endswith("[bot]"):
            return False
        return self.author.lower() in [o.lower() for o in self.cfg.get("owners", [])]


# --------------------------------------------------------------------------- diff handling


def parse_diff(text: str) -> list:
    """Parse ``git diff -U0 --no-renames`` output into Change objects."""
    changes: list = []
    cur: Optional[Change] = None
    old_ln = new_ln = 0
    for raw in text.split("\n"):
        if raw.startswith("diff --git "):
            cur = None
            m = re.match(r"diff --git a/(.*) b/(.*)$", raw)
            if m:
                cur = Change(path=m.group(2), status="M")
                changes.append(cur)
            continue
        if cur is None:
            continue
        if raw.startswith("new file mode"):
            cur.status = "A"
        elif raw.startswith("deleted file mode"):
            cur.status = "D"
        elif raw.startswith("+++ "):
            if raw.startswith("+++ b/"):
                cur.path = raw[6:]
            continue
        elif raw.startswith("--- "):
            if cur.status == "D" and raw.startswith("--- a/"):
                cur.path = raw[6:]
            continue
        elif raw.startswith("@@"):
            m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
            if m:
                old_ln, new_ln = int(m.group(1)), int(m.group(2))
        elif raw.startswith("+") and not raw.startswith("+++"):
            cur.added.append((new_ln, raw[1:]))
            new_ln += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            cur.removed.append((old_ln, raw[1:]))
            old_ln += 1
    return changes


def git(repo: str, *args: str, check: bool = True) -> str:
    p = subprocess.run(["git", "-C", repo, "-c", "core.quotepath=off", *args], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])} failed: {p.stderr.strip()[:300]}")
    return p.stdout


def collect_changes(repo: str, base: str, head: str) -> list:
    return parse_diff(git(repo, "diff", "-U0", "--no-color", "--no-renames", "--no-ext-diff", base, head))


def make_reader(repo: str, rev: str) -> Callable[[str], Optional[str]]:
    def read(path: str) -> Optional[str]:
        p = subprocess.run(["git", "-C", repo, "show", f"{rev}:{path}"], capture_output=True, text=True)
        return p.stdout if p.returncode == 0 else None
    return read


# --------------------------------------------------------------------------- checks


def _sev(ctx: Context, owner_downgrades: bool) -> str:
    return WARNING if (owner_downgrades and ctx.author_is_owner) else ERROR


def check_protected_paths(changes, ctx: Context) -> list:
    out = []
    if ctx.cfg is None:
        return out
    owners = ctx.cfg.get("owners", [])
    for o in owners:
        if str(o).endswith("[bot]"):
            out.append(Finding("protected-paths", ERROR,
                               f"owners lists a bot identity ({o}); the bot must never be an owner"))
    for c in changes:
        pause = laneconfig.path_matches(laneconfig.PAUSE_FLAG_PATTERN, c.path)
        hit = (c.status == "D") if pause else laneconfig.is_protected(c.path, ctx.cfg)
        if not hit:
            continue
        what = "removal of pause flag" if pause else "protected path"
        if ctx.author_is_owner:
            continue
        out.append(Finding("protected-paths", ERROR,
                           f"{what} changed by non-owner '{ctx.author}': only an owner may change this, "
                           f"through a needs-human PR", c.path))
    return out


def _is_test_path(path: str) -> bool:
    return any(r.search(path) for r in TEST_PATH_RES)


def _number(s: str) -> float:
    return float(s)


def check_weakened(changes, ctx: Context) -> list:
    out = []
    sev = _sev(ctx, owner_downgrades=True)
    added_paths = {c.path for c in changes if c.status == "A"}
    added_basenames = {os.path.basename(p) for p in added_paths}
    for c in changes:
        # edits to branch-protection or ruleset config
        if any(r.search(c.path) for r in PROTECTION_CONFIG_RES):
            out.append(Finding("weakened-checks", sev, "branch-protection or ruleset configuration changed", c.path))
        # deleted tests
        if c.status == "D" and _is_test_path(c.path) and os.path.basename(c.path) not in added_basenames:
            out.append(Finding("weakened-checks", sev, "test file deleted", c.path))
        is_doc = c.path.endswith((".md", ".rst", ".txt"))
        for ln, text in c.added:
            if is_doc:
                continue
            for rx, label in SKIP_MARKERS:
                if rx.search(text):
                    out.append(Finding("weakened-checks", sev, f"test disabled or narrowed: {label}", c.path, ln))
            for rx, label in BYPASS_MARKERS:
                if rx.search(text):
                    out.append(Finding("weakened-checks", sev, f"check bypass added: {label}", c.path, ln))
            if BLANKET_LINT_RE.search(text):
                out.append(Finding("weakened-checks", sev, "blanket lint/type-check suppression added", c.path, ln))
            if CI_FILE_RE.search(c.path):
                if re.search(r"continue-on-error:\s*true", text):
                    out.append(Finding("weakened-checks", sev, "CI step made non-blocking (continue-on-error)", c.path, ln))
                if re.search(r"\|\|\s*true\b", text) and CHECK_CMD_RE.search(text):
                    out.append(Finding("weakened-checks", sev, "test or lint command made non-blocking (|| true)", c.path, ln))
                if WORKFLOW_RE.search(c.path) and re.search(r"^\s*(-\s*)?if:\s*(false|\$\{\{\s*false\s*\}\})\s*$", text):
                    out.append(Finding("weakened-checks", sev, "workflow step disabled with 'if: false'", c.path, ln))
        # thresholds lowered (or removed), upper limits raised
        out += _threshold_findings(c, sev)
        # net removal of test cases
        if c.status == "M" and _is_test_path(c.path):
            rem = sum(1 for _, t in c.removed if TEST_DEF_RE.match(t))
            add = sum(1 for _, t in c.added if TEST_DEF_RE.match(t))
            if rem > add:
                out.append(Finding("weakened-checks", sev,
                                   f"test cases removed ({rem} removed, {add} added)", c.path))
        # test or lint commands removed from CI
        if CI_FILE_RE.search(c.path) and c.status in ("M", "D"):
            norm = lambda s: re.sub(r"\s+", " ", s.strip())
            added_norm = {norm(t) for _, t in c.added}
            for ln, text in c.removed:
                if CHECK_CMD_RE.search(text) and norm(text) not in added_norm and not text.strip().startswith("#"):
                    out.append(Finding("weakened-checks", sev, "test or lint command removed from CI or scripts", c.path, ln))
    return out


def _threshold_findings(c: Change, sev: str) -> list:
    out = []
    if c.status == "D":
        return out
    for rx, lower in ((LOWER_KEYS, True), (LOWER_NESTED, True), (UPPER_KEYS, False)):
        old = {}
        for _, t in c.removed:
            for m in rx.finditer(t):
                old[m.group(1)] = _number(m.group(2))
        new = {}
        for ln, t in c.added:
            for m in rx.finditer(t):
                new[m.group(1)] = (_number(m.group(2)), ln)
        for key, ov in old.items():
            if key in new:
                nv, ln = new[key]
                if (lower and nv < ov) or (not lower and nv > ov):
                    out.append(Finding("weakened-checks", sev,
                                       f"threshold '{key}' {'lowered' if lower else 'raised'} from {ov:g} to {nv:g}",
                                       c.path, ln))
            elif lower:
                out.append(Finding("weakened-checks", sev, f"threshold '{key}' removed", c.path))
    return out


def check_secrets(changes, ctx: Context) -> list:
    out = []
    for c in changes:
        if c.status == "D":
            continue
        for ln, text in c.added:
            for label, rx in SECRET_PATTERNS:
                m = rx.search(text)
                if m:
                    out.append(Finding("secrets", ERROR, f"possible {label} committed (value not shown)", c.path, ln))
            m = GENERIC_SECRET_RE.search(text)
            if m and not PLACEHOLDER_RE.search(m.group(1)):
                out.append(Finding("secrets", ERROR, "possible hard-coded credential in an assignment (value not shown)", c.path, ln))
    return out


def check_lock(ctx: Context) -> list:
    if ctx.lock_status is None:
        return []
    try:
        st = ctx.lock_status()
    except Exception as e:  # cannot reach the forge: do not fail every PR on a network blip
        return [Finding("lock", WARNING, f"could not read the lock to check its age: {str(e)[:160]}")]
    if st.get("held") and st.get("alarm"):
        return [Finding("lock", ERROR, "the lock is older than 2 x lock_ttl_minutes: a lane run is stuck or crashed; "
                                       "an owner should inspect refs/laneguard/lock")]
    return []


def check_pin(ctx: Context) -> list:
    text = ctx.read_head(".laneguard/plugin.lock")
    if text is None:
        return [Finding("engine-pin", ERROR, ".laneguard/plugin.lock is missing: the engine must be pinned to a commit SHA",
                        ".laneguard/plugin.lock")]
    try:
        data = laneconfig.loads(text) or {}
    except laneconfig.YamlError as e:
        return [Finding("engine-pin", ERROR, f"plugin.lock is not valid: {e}", ".laneguard/plugin.lock")]
    sha = str(data.get("sha", "")) if isinstance(data, dict) else ""
    if not laneconfig.is_full_sha(sha):
        return [Finding("engine-pin", ERROR, "engine pin must be a full 40-character lowercase commit SHA "
                                             "(branches, tags and short SHAs are not accepted)", ".laneguard/plugin.lock")]
    return []


def check_head_config(ctx: Context) -> list:
    text = ctx.read_head(laneconfig.CONFIG_PATH)
    if text is None:
        return []
    try:
        cfg = laneconfig._merge_defaults(laneconfig.loads(text))
    except laneconfig.YamlError as e:
        return [Finding("config", ERROR, f"config.yaml does not parse: {e}", laneconfig.CONFIG_PATH)]
    return [Finding("config", ERROR, f"config.yaml invalid: {p}", laneconfig.CONFIG_PATH) for p in laneconfig.validate(cfg)]


def check_lane_scope(changes, ctx: Context) -> list:
    if ctx.cfg is None:
        return []
    lane_names = {laneconfig.lane_for_label(ctx.cfg, l) for l in ctx.labels} - {None}
    if not lane_names:
        return []
    if len(lane_names) > 1:
        return [Finding("lane-scope", ERROR, f"PR carries labels for more than one lane ({', '.join(sorted(lane_names))})")]
    lane = next(iter(lane_names))
    owns = ctx.cfg["lanes"][lane].get("owns", [])
    outside = [c.path for c in changes if not any(laneconfig.path_matches(o, c.path) or c.path == o.rstrip("/") for o in owns)]
    if not outside:
        return []
    trusted_issue = None
    for n in ctx.linked_issues:
        if ctx.trust_issue is None:
            break
        try:
            if ctx.trust_issue(n).get("trusted"):
                trusted_issue = n
                break
        except Exception:
            continue
    if trusted_issue is not None:
        return []
    shown = ", ".join(outside[:5]) + (f" and {len(outside) - 5} more" if len(outside) > 5 else "")
    why = ("no linked issue was found" if not ctx.linked_issues else
           "none of the linked issues is owner-created or owner-labelled" if ctx.trust_issue else
           "linked issues could not be verified offline")
    return [Finding("lane-scope", ERROR,
                    f"lane '{lane}' PR changes paths outside its owns ({shown}) and {why}")]


# --------------------------------------------------------------------------- orchestration


def run_checks(changes, ctx: Context) -> list:
    findings: list = []
    if ctx.cfg is None:
        findings.append(Finding("bootstrap", WARNING,
                                "no .laneguard/config.yaml on the base commit: running secret scanning only. "
                                "An owner must review this PR; protected-path rules apply once config is on the default branch"))
        findings += check_secrets(changes, ctx)
        findings += check_pin(ctx)
        return findings
    findings += check_protected_paths(changes, ctx)
    findings += check_weakened(changes, ctx)
    findings += check_secrets(changes, ctx)
    findings += check_lock(ctx)
    findings += check_pin(ctx)
    findings += check_head_config(ctx)
    findings += check_lane_scope(changes, ctx)
    return findings


def render(findings: list) -> str:
    errors = [f for f in findings if f.severity == ERROR]
    warns = [f for f in findings if f.severity == WARNING]
    head = "laneguard-guard / check  " + ("FAILED" if errors else "PASSED")
    lines = [head]
    for label, group in (("error", errors), ("warning", warns)):
        for f in group:
            loc = f"{f.path}:{f.line}" if f.path and f.line else f.path
            lines.append(f"  {label:7} [{f.check}] {f.message}" + (f"  ({loc})" if loc else ""))
    if not findings:
        lines.append("  no findings")
    return "\n".join(lines)


LINK_RE = re.compile(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+(?:[\w.-]+/[\w.-]+)?#(\d+)")


def linked_issues_from_body(body: str) -> list:
    return sorted({int(n) for n in LINK_RE.findall(body or "")})


def build_context(repo: str, base: str, head: str, author: str, author_type: str, labels, linked,
                  offline: bool, trust_issue=None, lock_status=None) -> Context:
    read_base = make_reader(repo, base)
    cfg = None
    text = read_base(laneconfig.CONFIG_PATH)
    if text is not None:
        cfg = laneconfig._merge_defaults(laneconfig.loads(text))
    ctx = Context(cfg=cfg, author=author, author_type=author_type, labels=tuple(labels),
                  linked_issues=tuple(linked), read_head=make_reader(repo, head), read_base=read_base,
                  trust_issue=trust_issue, lock_status=lock_status)
    if cfg is not None and not offline:
        try:
            import forge as forge_mod
            f = forge_mod.from_config(repo)
            ctx.trust_issue = ctx.trust_issue or f.trust_issue
        except Exception:
            pass
        try:
            import lock as lock_mod
            store = lock_mod.LockStore(repo, clock=lock_mod.ForgeClock(), ttl_minutes=cfg["limits"]["lock_ttl_minutes"])
            ctx.lock_status = ctx.lock_status or store.status
        except Exception:
            pass
    return ctx


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="check.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--author", required=True)
    ap.add_argument("--author-type", default="User", choices=["User", "Bot", "Organization"])
    ap.add_argument("--labels", default="")
    ap.add_argument("--linked-issues", default="")
    ap.add_argument("--pr-body-file")
    ap.add_argument("--offline", action="store_true", help="skip checks that need the forge (lock age, issue trust)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        labels = [l.strip() for l in args.labels.split(",") if l.strip()]
        linked = [int(x) for x in args.linked_issues.split(",") if x.strip()]
        if args.pr_body_file:
            linked = sorted(set(linked) | set(linked_issues_from_body(Path(args.pr_body_file).read_text())))
        changes = collect_changes(args.repo, args.base, args.head)
        ctx = build_context(args.repo, args.base, args.head, args.author, args.author_type, labels, linked, args.offline)
        findings = run_checks(changes, ctx)
    except (RuntimeError, OSError, ValueError, laneconfig.YamlError) as e:
        print(f"check.py error: {e}", file=sys.stderr)
        return 2
    report = render(findings)
    if args.json:
        print(json.dumps({"passed": not any(f.severity == ERROR for f in findings),
                          "findings": [f.to_dict() for f in findings]}, indent=2))
    else:
        print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write("```\n" + report + "\n```\n")
        except OSError:
            pass
    return 1 if any(f.severity == ERROR for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
