#!/usr/bin/env python3
"""check_agents.py: static conformance check of agents/*.md against docs/design-spec.md (section 8).

Python 3, standard library only. It reads files; it never runs an agent.

Checks:
  1. frontmatter has name (matching the filename), description, tools, model
  2. tools respect the access column of the spec's agents table
       - read-only agents: no Edit, Write, NotebookEdit; Bash only where the spec needs it
       - design-pipeline agents: Write allowed, no Edit, no Bash
       - implementer is the only agent with Edit
  3. reviewers use a different model tier than the implementer
  4. every lane in config (dev, security, design by default) has a reviewer-<lane> agent
  5. every agent body mentions untrusted-data handling (strict wording for agents that read raw
     issue text, looser for agents that receive only derived input)

Usage: check_agents.py [--agents DIR] [--json]
Exit codes: 0 no problems; 1 problems found; 2 usage error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "guard"))

TIER = {"haiku": "fastest", "sonnet": "mid", "opus": "strongest"}
# Spec section 8 agents table. Access: read-only | docs-write | writer
# bash_ok: the spec's Access column explicitly gives the agent a command surface (validator: "read-only
#          plus configured validation commands"; implementer: the writer). Observer and triager are plain
#          "read-only" in the table but need Bash to call forge.py (read-only subcommands), so Bash on them
#          is accepted here, not reported. Their "read-only" is instruction-level for Bash: the project
#          allowlist grants forge.py to every agent, and the enforced limit is forge.py's own write
#          allow-list plus branch protection (see docs/security-model.md and issue #6).
SPEC = {
    "architect":         {"access": "docs-write", "bash_ok": False, "tier": "strongest"},
    "planner":           {"access": "docs-write", "bash_ok": False, "tier": "strongest"},
    "observer":          {"access": "read-only",  "bash_ok": True,   "tier": "fastest"},
    "triager":           {"access": "read-only",  "bash_ok": True,  "tier": "mid"},
    "gatekeeper":        {"access": "read-only",  "bash_ok": False, "tier": "mid"},
    "implementer":       {"access": "writer",     "bash_ok": True,  "tier": "mid"},
    "validator":         {"access": "read-only",  "bash_ok": True,  "tier": "fastest"},
    "reviewer-dev":      {"access": "read-only",  "bash_ok": False, "tier": "strongest"},
    "reviewer-security": {"access": "read-only",  "bash_ok": False, "tier": "strongest"},
    "reviewer-design":   {"access": "read-only",  "bash_ok": False, "tier": "strongest"},
}
# Agents that read raw issue/PR/comment text must say it is untrusted data.
STRICT_UNTRUSTED = {"observer", "triager"}
STRICT_RE = re.compile(r"(?i)\bdata,? not instructions?\b|\buntrusted\b")
# Everyone else only has to show awareness: untrusted/data-not-instructions, a rule not to follow or act on
# embedded text, that raw issue text is withheld, or that its input is the derived task brief or an
# owner-approved document. The bare word "brief" is not enough: the phrase must say where the brief came from
# ("task brief (...)", "the triager's brief", "owner-approved").
LOOSE_RE = re.compile(r"(?i)untrusted|data,? not instructions?|raw (issue|comment)|not given (issue|raw)|never sees? raw|"
                      r"ignore (it|them|that)[^.]*flag|text that tells you|"
                      r"(do not|don't|never) (follow|act on|obey)[^.]*(text|instruction|comment)|treat[^.]* as data|"
                      r"owner[- ]approve[sd]|approved (brief|spec|plan)|triager'?s (task )?brief|task brief \(")
WRITE_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}


def parse(path: Path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        return None, text
    fm = {}
    for line in m.group(1).splitlines():
        k, sep, v = line.partition(":")
        if sep:
            fm[k.strip()] = v.strip()
    return fm, m.group(2)


def lane_names():
    try:
        import laneconfig
        return [n for n in laneconfig.PROFILE_LANES.get("full", [])] or ["dev", "security", "design"]
    except Exception:
        return ["dev", "security", "design"]


def check(agents_dir: Path) -> list:
    problems = []

    def bad(agent, msg):
        problems.append({"agent": agent, "problem": msg})

    files = sorted(agents_dir.glob("*.md"))
    names = {f.stem for f in files}
    for missing in sorted(set(SPEC) - names):
        bad(missing, "agent listed in the spec is missing from agents/")
    for extra in sorted(names - set(SPEC)):
        bad(extra, "agent file is not in the spec's agents table (project lanes may add reviewer-<lane>; confirm)")

    fms = {}
    for f in files:
        name = f.stem
        fm, body = parse(f)
        if fm is None:
            bad(name, "no YAML frontmatter")
            continue
        fms[name] = fm
        for key in ("name", "description", "tools", "model"):
            if not fm.get(key):
                bad(name, f"frontmatter '{key}' missing or empty")
        if fm.get("name") and fm["name"] != name:
            bad(name, f"frontmatter name '{fm['name']}' does not match filename")
        tools = {t.strip() for t in fm.get("tools", "").split(",") if t.strip()}
        model = fm.get("model", "")
        spec = SPEC.get(name)
        if model and model not in TIER:
            bad(name, f"model '{model}' is not a known tier alias ({', '.join(TIER)})")
        if spec:
            if model in TIER and TIER[model] != spec["tier"]:
                bad(name, f"model tier is {TIER[model]} ({model}), spec default is {spec['tier']}")
            if "Bash" in tools and not spec["bash_ok"]:
                bad(name, "tools include Bash but the spec gives this agent no command access")
            if "Bash" not in tools and spec["bash_ok"]:
                bad(name, "tools lack Bash but the spec gives this agent a command surface")
            if spec["access"] == "read-only" and tools & WRITE_TOOLS:
                bad(name, f"read-only agent has write tools: {', '.join(sorted(tools & WRITE_TOOLS))}")
            if spec["access"] == "docs-write" and ("Edit" in tools):
                bad(name, "docs-write agent has Edit (spec: docs write only)")
            if spec["access"] == "docs-write" and "Write" not in tools:
                bad(name, "docs-write agent has no Write tool")
            if name != "implementer" and "Edit" in tools:
                bad(name, "only the implementer may have Edit (spec: one writer)")
        if "Task" in tools or "Agent" in tools:
            bad(name, "subagents must not spawn agents (spec rule 3)")
        rx = STRICT_RE if name in STRICT_UNTRUSTED else LOOSE_RE
        if not rx.search(body):
            kind = "states that issue/PR/comment text is untrusted data" if name in STRICT_UNTRUSTED \
                else "mentions untrusted-data handling or that raw issue text is withheld"
            bad(name, f"body does not mention untrusted-data handling (expected: {kind})")

    impl = fms.get("implementer", {}).get("model")
    for name, fm in fms.items():
        if name.startswith("reviewer-") and impl and fm.get("model") == impl:
            bad(name, f"reviewer uses the same model ({impl}) as the implementer")
    for lane in lane_names():
        if f"reviewer-{lane}" not in names:
            bad(f"reviewer-{lane}", f"lane '{lane}' has no reviewer-{lane} agent")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="check_agents.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--agents", default=str(ROOT / "agents"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    d = Path(args.agents)
    if not d.is_dir():
        print(f"not a directory: {d}", file=sys.stderr)
        return 2
    problems = check(d)
    if args.json:
        print(json.dumps(problems, indent=2))
    else:
        n = len(list(d.glob("*.md")))
        print(f"checked {n} agent files in {d}")
        for p in problems:
            print(f"  PROBLEM {p['agent']}: {p['problem']}")
        print("no problems" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
