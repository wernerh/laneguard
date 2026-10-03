#!/usr/bin/env python3
"""allowlist.py: generate and verify the tool allowlist in .claude/settings.json.

The ``tools:`` line in an agent file states intent; THIS file is the enforced limit. It is generated
from ``.laneguard/config.yaml`` so nobody maintains it by hand, ``.claude/**`` is a protected path so
a lane cannot edit it, and ``doctor`` verifies it matches what this script would generate.

To be explicit about the limit: this is permission scoping, not a sandbox. A permitted interpreter
(for example the project's own test runner) can still do whatever code can do. Run lanes on
ephemeral runners or containers if that matters to you. ``check.py`` is the backstop for diffs.

Python 3, standard library only.

Usage:
  allowlist.py generate [--root DIR] [--write]   print the settings, or write .claude/settings.json
  allowlist.py verify   [--root DIR]             exit 1 if .claude/settings.json differs from generated
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import laneconfig  # noqa: E402

SETTINGS_PATH = ".claude/settings.json"
GUARD = ".laneguard/guard"

CLOUD_AND_DEPLOY_TOOLS = [
    "aws", "gcloud", "az", "terraform", "tofu", "pulumi", "kubectl", "helm", "flyctl", "fly", "vercel",
    "netlify", "heroku", "wrangler", "doctl", "railway", "supabase", "firebase", "serverless", "sam", "cdk",
]
NETWORK_TOOLS = ["curl", "wget", "nc", "ncat", "ssh", "scp", "sftp", "rsync", "ftp", "telnet", "socat"]
INSTALL_AND_PUBLISH = [
    "npm install", "npm i", "npm add", "npm publish", "npx", "yarn add", "yarn publish", "pnpm add", "pnpm publish",
    "pip install", "pip3 install", "python -m pip install", "python3 -m pip install", "poetry add", "uv add",
    "uv pip install", "cargo add", "cargo install", "cargo publish", "go get", "go install", "gem install",
    "twine", "docker push", "docker login", "apt install", "apt-get install", "brew install",
]
HISTORY_AND_FORCE = [
    "git push --force", "git push -f", "git push --force-with-lease", "git push --delete", "git push origin :",
    "git push origin +", "git filter-branch", "git filter-repo", "git rebase", "git reset --hard",
    "git update-ref", "git replace", "git reflog expire", "git gc --prune",
]
ENV_AND_SECRETS_READS = [
    "env", "printenv", "export", "set", "declare -x", "cat .env", "cat ~/.ssh", "cat ~/.aws", "cat ~/.config/gh",
    "cat ~/.netrc", "cat ~/.npmrc", "sudo", "su",
]
SECRET_READ_PATHS = [
    "/.env", "/.env.*", "/**/.env", "/**/.env.*", "~/.ssh/**", "~/.aws/**", "~/.config/gh/**",
    "~/.netrc", "~/.npmrc", "~/.gnupg/**", "~/.docker/config.json", "~/.kube/**",
]


def _rule_path(pattern: str) -> str:
    return "/" + pattern.lstrip("/")


def branch_prefixes(cfg: dict) -> list:
    out = []
    for lane in cfg.get("lanes", {}).values():
        pre = f"{lane['label']}/"
        if pre not in out:
            out.append(pre)
    return out


def _dedupe(items) -> list:
    seen, out = set(), []
    for i in items:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def generate(cfg: dict) -> dict:
    allow = ["Read", "Grep", "Glob", "Edit", "Write"]
    for cmd in (cfg.get("validation") or {}).values():
        if isinstance(cmd, str) and cmd.strip():
            allow.append(f"Bash({cmd.strip()})")
    for sub in ("status", "diff", "log", "show", "branch", "add", "commit", "fetch", "ls-files", "rev-parse",
                "checkout -b", "switch -c", "stash list"):
        allow.append(f"Bash(git {sub}:*)")
    for pre in branch_prefixes(cfg):
        allow.append(f"Bash(git push origin {pre}*)")
        allow.append(f"Bash(git push -u origin {pre}*)")
    # forge_read.py is the read-only face of forge.py for the observer, triager and validator. The allowlist is
    # project-wide, so forge.py (writes) stays granted for the orchestrator; the split is enforced by the agent
    # prompts plus evals/conformance/check_agents.py, and visible in logs and hooks because the scripts differ.
    for script in ("forge.py", "forge_read.py", "lock.py", "history.py", "check.py", "doctor.py"):
        allow.append(f"Bash(python3 {GUARD}/{script}:*)")
    allow += ["Bash(ls:*)", "Bash(wc:*)", "Bash(pwd)"]

    deny = []
    for pattern in laneconfig.protected_paths(cfg):
        deny.append(f"Edit({_rule_path(pattern)})")
        deny.append(f"Write({_rule_path(pattern)})")
    deny += ["Bash(rm .laneguard/PAUSED*)", "Bash(git rm .laneguard/PAUSED*)", "Bash(rm -rf:*)"]
    deny += [f"Bash({c}:*)" for c in HISTORY_AND_FORCE]
    deny += ["Bash(gh:*)", "WebFetch", "WebSearch"]
    deny += [f"Bash({t}:*)" for t in NETWORK_TOOLS]
    deny += [f"Bash({c}:*)" for c in INSTALL_AND_PUBLISH]
    deny += [f"Bash({t}:*)" for t in CLOUD_AND_DEPLOY_TOOLS]
    deny += [f"Bash({c}:*)" for c in ENV_AND_SECRETS_READS]
    deny += [f"Read({p})" for p in SECRET_READ_PATHS]
    return {"permissions": {"allow": _dedupe(allow), "deny": _dedupe(deny), "defaultMode": "default"}}


def render(settings: dict) -> str:
    return json.dumps(settings, indent=2) + "\n"


def verify(cfg: dict, actual_text: str) -> list:
    """Return problems; empty list means .claude/settings.json matches the generated allowlist."""
    try:
        actual = json.loads(actual_text)
    except ValueError as e:
        return [f"{SETTINGS_PATH} is not valid JSON: {e}"]
    want = generate(cfg)["permissions"]
    got = (actual.get("permissions") or {}) if isinstance(actual, dict) else {}
    problems = []
    for kind in ("allow", "deny"):
        w, g = want[kind], got.get(kind, [])
        extra = [x for x in g if x not in w]
        missing = [x for x in w if x not in g]
        if kind == "allow":
            problems += [f"allows more than the generated list: {x}" for x in extra]
            problems += [f"missing allow rule: {x}" for x in missing]
        else:
            problems += [f"missing deny rule (protection removed): {x}" for x in missing]
            problems += [f"unexpected deny rule: {x}" for x in extra]
    if got.get("defaultMode", "default") not in ("default",):
        problems.append(f"permissions.defaultMode is {got.get('defaultMode')!r}; it must be 'default'")
    for key in actual if isinstance(actual, dict) else []:
        if key in ("hooks", "env", "apiKeyHelper", "enableAllProjectMcpServers", "enabledMcpjsonServers"):
            problems.append(f"settings key '{key}' can widen what a lane may do and is not generated")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="allowlist.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate"); g.add_argument("--root", default="."); g.add_argument("--write", action="store_true")
    v = sub.add_parser("verify"); v.add_argument("--root", default=".")
    args = ap.parse_args(argv)
    try:
        cfg = laneconfig.load_config(root=args.root)
    except (FileNotFoundError, laneconfig.YamlError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if args.cmd == "generate":
        text = render(generate(cfg))
        if args.write:
            dest = Path(args.root) / SETTINGS_PATH
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")
            print(f"wrote {dest}")
        else:
            sys.stdout.write(text)
        return 0
    path = Path(args.root) / SETTINGS_PATH
    if not path.exists():
        print(f"{SETTINGS_PATH} is missing")
        return 1
    problems = verify(cfg, path.read_text(encoding="utf-8"))
    for p in problems:
        print(f"- {p}")
    print("allowlist matches" if not problems else f"{len(problems)} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
