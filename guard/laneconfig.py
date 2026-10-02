#!/usr/bin/env python3
"""laneconfig: configuration loader and shared constants for the Laneguard guard scripts.

Python 3, standard library only. The guard scripts must run on a bare CI runner,
so this module ships a small YAML-subset reader instead of depending on PyYAML.

Supported YAML subset (everything the Laneguard templates use):
  * block mappings and block sequences, nested by indentation
  * flow sequences [a, b] and flow mappings {k: v, k2: v2}, nested
  * plain, single-quoted and double-quoted scalars; ints, floats, true/false, null
  * literal (|) and folded (>) block scalars
  * comments introduced by "#" outside quotes
Anchors, tags, multi-document streams and complex keys are not supported and raise
YamlError rather than being silently misread.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CONFIG_PATH = ".laneguard/config.yaml"

# Paths only an owner may change (spec section 10). Projects may add to this list, never remove.
BASE_PROTECTED_PATHS = [
    ".laneguard/guard/**",
    ".laneguard/config.yaml",
    ".laneguard/plugin.lock",
    ".laneguard/scaffold.version",
    ".github/workflows/laneguard-*.yml",
    ".github/CODEOWNERS",
    ".claude/**",
]
# Removal (not creation) of these is protected.
PAUSE_FLAG_PATTERN = ".laneguard/PAUSED*"

VALID_MODES = ("observe", "propose", "autonomous")
VALID_PROFILES = ("minimal", "standard", "full")
VALID_MODEL_TIERS = ("fastest", "mid", "strongest")
AGENT_NAMES = (
    "architect", "planner", "observer", "triager", "gatekeeper",
    "implementer", "validator", "reviewer-dev", "reviewer-security", "reviewer-design",
)
DEFAULT_MODELS = {
    "architect": "strongest", "planner": "strongest", "observer": "fastest",
    "triager": "mid", "gatekeeper": "mid", "implementer": "mid", "validator": "fastest",
    "reviewer-dev": "strongest", "reviewer-security": "strongest", "reviewer-design": "strongest",
}
DEFAULT_LIMITS = {
    "run_max_minutes": 30, "lock_ttl_minutes": 45, "heartbeat_minutes": 10, "claim_expiry_hours": 24,
}
DEFAULT_BUDGETS = {
    "per_run": {"max_turns": 60, "max_tokens": 2000000},
    "monthly_cost_ceiling_usd": 200,
    "max_open_prs_per_lane": 2,
    "max_issues_created_per_day": 5,
}
DEFAULT_BREAKER = {"consecutive_failures": 3, "same_pr_failures": 2}
PROFILE_LANES = {
    "minimal": ["dev"],
    "standard": ["dev", "security"],
    "full": ["dev", "security", "design"],
}
DEFAULT_LANES = {
    "dev": {"label": "laneguard", "schedule": "every 2h", "owns": ["PROJECT_STATE.md"], "mode": "propose"},
    "security": {"label": "laneguard-security", "schedule": "every 4h", "owns": ["docs/security/"], "mode": "propose"},
    "design": {"label": "laneguard-design", "schedule": "every 4h", "owns": ["docs/design/"], "mode": "propose"},
}
# Universal human gates (spec section 9). Projects may add (extra_gates), never remove.
BASE_GATES = [
    "spending money",
    "creating cloud resources",
    "identity-provider apps or secrets",
    "production deploys",
    "contacting anyone other than the owner",
    "publishing externally",
    "destructive or irreversible actions",
    "expensive-to-reverse architecture",
    "raising a lane's mode or limits",
]

FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def is_full_sha(value: str) -> bool:
    return bool(FULL_SHA_RE.match(str(value).strip()))


# --------------------------------------------------------------------------- YAML subset


class YamlError(ValueError):
    pass


class _Row:
    __slots__ = ("indent", "text", "lineno")

    def __init__(self, indent: int, text: str, lineno: int):
        self.indent = indent
        self.text = text
        self.lineno = lineno  # 0-based index into the raw line list


def _strip_comment(s: str) -> str:
    out = []
    quote = None
    i = 0
    while i < len(s):
        c = s[i]
        if quote:
            out.append(c)
            if c == "\\" and quote == '"' and i + 1 < len(s):
                out.append(s[i + 1])
                i += 1
            elif c == quote:
                if quote == "'" and i + 1 < len(s) and s[i + 1] == "'":
                    out.append("'")
                    i += 1
                else:
                    quote = None
        else:
            if c in ("'", '"') and (not out or out[-1] in " \t[{,:") :
                quote = c
                out.append(c)
            elif c == "#" and (i == 0 or s[i - 1] in " \t"):
                break
            else:
                out.append(c)
        i += 1
    return "".join(out).rstrip()


def _unescape_double(s: str) -> str:
    table = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/", "0": "\0"}
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", s[i + 2:i + 6]):
                out.append(chr(int(s[i + 2:i + 6], 16)))
                i += 6
                continue
            if nxt not in table:
                raise YamlError(f"unsupported escape \\{nxt}")
            out.append(table[nxt])
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _scalar(tok: str):
    tok = tok.strip()
    if tok == "":
        return None
    if tok[0] == '"':
        if len(tok) < 2 or tok[-1] != '"':
            raise YamlError(f"unterminated double-quoted string: {tok!r}")
        return _unescape_double(tok[1:-1])
    if tok[0] == "'":
        if len(tok) < 2 or tok[-1] != "'":
            raise YamlError(f"unterminated single-quoted string: {tok!r}")
        return tok[1:-1].replace("''", "'")
    if tok[0] in "&*!":
        raise YamlError(f"anchors, aliases and tags are not supported: {tok!r}")
    low = tok.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "~"):
        return None
    if re.fullmatch(r"[-+]?\d+", tok):
        return int(tok)
    if re.fullmatch(r"[-+]?(\d+\.\d*|\.\d+)([eE][-+]?\d+)?|[-+]?\d+[eE][-+]?\d+", tok):
        return float(tok)
    return tok


class _Flow:
    """Recursive-descent parser for flow collections: [a, b] and {k: v}."""

    def __init__(self, s: str):
        self.s = s
        self.i = 0

    def _ws(self):
        while self.i < len(self.s) and self.s[self.i] in " \t":
            self.i += 1

    def parse(self):
        v = self._value()
        self._ws()
        if self.i != len(self.s):
            raise YamlError(f"trailing characters in flow value: {self.s[self.i:]!r}")
        return v

    def _value(self):
        self._ws()
        if self.i >= len(self.s):
            return None
        c = self.s[self.i]
        if c == "[":
            return self._seq()
        if c == "{":
            return self._map()
        return self._atom(stop=",]}")

    def _atom(self, stop: str, is_key: bool = False):
        self._ws()
        start = self.i
        if self.i < len(self.s) and self.s[self.i] in ("'", '"'):
            q = self.s[self.i]
            self.i += 1
            while self.i < len(self.s):
                if self.s[self.i] == "\\" and q == '"':
                    self.i += 2
                    continue
                if self.s[self.i] == q:
                    if q == "'" and self.i + 1 < len(self.s) and self.s[self.i + 1] == "'":
                        self.i += 2
                        continue
                    self.i += 1
                    return _scalar(self.s[start:self.i])
                self.i += 1
            raise YamlError(f"unterminated quoted string in flow value: {self.s!r}")
        while self.i < len(self.s):
            c = self.s[self.i]
            if c in stop:
                break
            if is_key and c == ":" and (self.i + 1 >= len(self.s) or self.s[self.i + 1] in " \t"):
                break
            self.i += 1
        return _scalar(self.s[start:self.i])

    def _seq(self):
        self.i += 1
        out = []
        while True:
            self._ws()
            if self.i >= len(self.s):
                raise YamlError("unterminated flow sequence")
            if self.s[self.i] == "]":
                self.i += 1
                return out
            out.append(self._value())
            self._ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1

    def _map(self):
        self.i += 1
        out = {}
        while True:
            self._ws()
            if self.i >= len(self.s):
                raise YamlError("unterminated flow mapping")
            if self.s[self.i] == "}":
                self.i += 1
                return out
            key = self._atom(stop=",}", is_key=True)
            self._ws()
            if self.i < len(self.s) and self.s[self.i] == ":":
                self.i += 1
                val = self._value()
            else:
                val = None
            out[key if isinstance(key, str) else str(key)] = val
            self._ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1


def _inline(text: str):
    text = text.strip()
    if text and text[0] in "[{":
        return _Flow(text).parse()
    return _scalar(text)


def _split_key(text: str):
    """Split 'key: rest' at the first unquoted ': ' (or trailing ':'). Returns (key, rest) or None."""
    quote = None
    depth = 0
    i = 0
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\" and quote == '"':
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in ("'", '"') and i == 0:
            quote = c
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
        elif c == ":" and depth <= 0 and (i + 1 == len(text) or text[i + 1] in " \t"):
            key = _scalar(text[:i]) if text[:i].strip() else ""
            return (key if isinstance(key, str) else str(key)), text[i + 1:].strip()
        i += 1
    return None


class _Parser:
    def __init__(self, text: str):
        self.raw = text.replace("\r\n", "\n").replace("\t", "    ").split("\n")
        self.rows: list[_Row] = []
        for n, line in enumerate(self.raw):
            stripped = _strip_comment(line)
            if stripped.strip() == "":
                continue
            if stripped.strip() in ("---",):
                continue
            indent = len(stripped) - len(stripped.lstrip(" "))
            self.rows.append(_Row(indent, stripped.strip(), n))
        self.pos = 0

    def _peek(self):
        return self.rows[self.pos] if self.pos < len(self.rows) else None

    def parse(self):
        if not self.rows:
            return {}
        first = self.rows[0]
        value = self._node(first.indent)
        if self.pos != len(self.rows):
            r = self.rows[self.pos]
            raise YamlError(f"line {r.lineno + 1}: unexpected content {r.text!r} (bad indentation?)")
        return value

    def _is_item(self, row: _Row) -> bool:
        return row.text == "-" or row.text.startswith("- ")

    def _node(self, indent: int):
        row = self._peek()
        if row is None:
            return None
        if self._is_item(row):
            return self._seq(indent)
        return self._map(indent)

    def _seq(self, indent: int):
        out = []
        while True:
            row = self._peek()
            if row is None or row.indent != indent or not self._is_item(row):
                break
            rest = row.text[1:].strip()
            if rest == "":
                self.pos += 1
                nxt = self._peek()
                if nxt is not None and nxt.indent > indent:
                    out.append(self._node(nxt.indent))
                else:
                    out.append(None)
                continue
            offset = row.text.index(rest, 1)
            if rest[0] not in "[{'\"" and _split_key(rest) is not None:
                # "- key: value" begins an inline mapping at a deeper column
                row.indent = indent + offset
                row.text = rest
                out.append(self._map(row.indent))
            else:
                self.pos += 1
                out.append(_inline(rest))
        return out

    def _map(self, indent: int):
        out = {}
        while True:
            row = self._peek()
            if row is None or row.indent != indent:
                break
            if self._is_item(row):
                break
            kv = _split_key(row.text)
            if kv is None:
                raise YamlError(f"line {row.lineno + 1}: expected 'key: value', got {row.text!r}")
            key, rest = kv
            if key in out:
                raise YamlError(f"line {row.lineno + 1}: duplicate key {key!r}")
            self.pos += 1
            if rest == "":
                nxt = self._peek()
                if nxt is not None and nxt.indent > indent:
                    out[key] = self._node(nxt.indent)
                elif nxt is not None and nxt.indent == indent and self._is_item(nxt):
                    out[key] = self._seq(indent)
                else:
                    out[key] = None
            elif rest[0] in "|>":
                out[key] = self._block_scalar(rest, row, indent)
            else:
                out[key] = _inline(rest)
        return out

    def _block_scalar(self, header: str, row: _Row, parent_indent: int):
        style = header[0]
        chomp = "-" if "-" in header[1:] else ("+" if "+" in header[1:] else "")
        lines = []
        i = row.lineno + 1
        while i < len(self.raw):
            ln = self.raw[i]
            if ln.strip() == "":
                lines.append("")
                i += 1
                continue
            ind = len(ln) - len(ln.lstrip(" "))
            if ind <= parent_indent:
                break
            lines.append(ln)
            i += 1
        # advance row pointer past consumed raw lines
        while self.pos < len(self.rows) and self.rows[self.pos].lineno < i:
            self.pos += 1
        content = [l for l in lines if l.strip() != ""]
        if not content:
            return ""
        base = min(len(l) - len(l.lstrip(" ")) for l in content)
        body = [l[base:] if l.strip() != "" else "" for l in lines]
        while body and body[-1] == "":
            body.pop()
        text = ("\n".join(body) if style == "|" else _fold(body))
        if chomp != "-":
            text += "\n"
        return text


def _fold(lines):
    out = []
    buf = []
    for l in lines:
        if l == "":
            if buf:
                out.append(" ".join(buf))
                buf = []
            out.append("")
        else:
            buf.append(l)
    if buf:
        out.append(" ".join(buf))
    return "\n".join(out)


def loads(text: str):
    """Parse a YAML-subset document into Python values."""
    return _Parser(text).parse()


def load_file(path) -> dict:
    data = loads(Path(path).read_text(encoding="utf-8"))
    return data if data is not None else {}


# --------------------------------------------------------------------------- config model


def _merge_defaults(cfg: dict) -> dict:
    cfg = dict(cfg)
    limits = dict(DEFAULT_LIMITS)
    limits.update(cfg.get("limits") or {})
    cfg["limits"] = limits
    budgets = json.loads(json.dumps(DEFAULT_BUDGETS))
    given = cfg.get("budgets") or {}
    for k, v in given.items():
        if isinstance(v, dict) and isinstance(budgets.get(k), dict):
            budgets[k].update(v)
        else:
            budgets[k] = v
    cfg["budgets"] = budgets
    breaker = dict(DEFAULT_BREAKER)
    breaker.update(cfg.get("circuit_breaker") or {})
    cfg["circuit_breaker"] = breaker
    models = dict(DEFAULT_MODELS)
    models.update(cfg.get("models") or {})
    cfg["models"] = models
    cfg.setdefault("approvals_required", 1)
    cfg.setdefault("mode", "propose")
    cfg.setdefault("owners", [])
    cfg["extra_gates"] = list(cfg.get("extra_gates") or [])
    cfg["extra_protected_paths"] = list(cfg.get("extra_protected_paths") or [])
    cfg["validation"] = dict(cfg.get("validation") or {})
    cfg["scheduler"] = dict(cfg.get("scheduler") or {"adapter": "github-actions"})
    lanes = {}
    for name, lane in (cfg.get("lanes") or {}).items():
        base = dict(DEFAULT_LANES.get(name, {}))
        base.update(lane or {})
        base.setdefault("mode", cfg["mode"])
        lanes[name] = base
    cfg["lanes"] = lanes
    return cfg


def validate(cfg: dict) -> list[str]:
    """Return a list of human-readable problems. Empty means the config is valid."""
    errs: list[str] = []
    for key in ("project", "repo"):
        if not cfg.get(key):
            errs.append(f"missing required key: {key}")
    repo = cfg.get("repo") or ""
    if repo and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", str(repo)):
        errs.append(f"repo must look like owner/name, got {repo!r}")
    owners = cfg.get("owners")
    if not isinstance(owners, list) or not owners or not all(isinstance(o, str) and o for o in owners):
        errs.append("owners must be a non-empty list of GitHub logins")
    ar = cfg.get("approvals_required")
    if not isinstance(ar, int) or isinstance(ar, bool) or ar < 1:
        errs.append("approvals_required must be an integer >= 1")
    elif isinstance(owners, list) and ar > len(owners):
        errs.append("approvals_required cannot exceed the number of owners")
    if cfg.get("profile") not in VALID_PROFILES:
        errs.append(f"profile must be one of {', '.join(VALID_PROFILES)}")
    if cfg.get("mode") not in VALID_MODES:
        errs.append(f"mode must be one of {', '.join(VALID_MODES)}")
    lanes = cfg.get("lanes")
    if not isinstance(lanes, dict) or not lanes:
        errs.append("lanes must define at least one lane")
    else:
        labels = {}
        for name, lane in lanes.items():
            if not re.fullmatch(r"[a-z][a-z0-9-]*", str(name)):
                errs.append(f"lane name {name!r} must be lowercase letters, digits and dashes")
            if not lane.get("label"):
                errs.append(f"lane {name}: label is required")
            elif lane["label"] in labels:
                errs.append(f"lane {name}: label {lane['label']!r} already used by lane {labels[lane['label']]}")
            else:
                labels[lane["label"]] = name
            if lane.get("mode") not in VALID_MODES:
                errs.append(f"lane {name}: mode must be one of {', '.join(VALID_MODES)}")
            owns = lane.get("owns")
            if not isinstance(owns, list) or not owns:
                errs.append(f"lane {name}: owns must be a non-empty list of paths")
            if not lane.get("schedule"):
                errs.append(f"lane {name}: schedule is required")
    lim = cfg.get("limits", {})
    for k in ("run_max_minutes", "lock_ttl_minutes", "heartbeat_minutes", "claim_expiry_hours"):
        if not isinstance(lim.get(k), int) or isinstance(lim.get(k), bool) or lim[k] <= 0:
            errs.append(f"limits.{k} must be a positive integer")
    if not errs or all("limits." not in e for e in errs):
        if lim["lock_ttl_minutes"] <= lim["run_max_minutes"]:
            errs.append("limits.lock_ttl_minutes must be greater than limits.run_max_minutes")
        if lim["heartbeat_minutes"] * 2 > lim["lock_ttl_minutes"]:
            errs.append("limits.heartbeat_minutes must be at most half of limits.lock_ttl_minutes")
    models = cfg.get("models", {})
    for agent, tier in models.items():
        if agent not in AGENT_NAMES and not str(agent).startswith("reviewer-"):
            errs.append(f"models.{agent}: unknown agent")
        if tier not in VALID_MODEL_TIERS:
            errs.append(f"models.{agent}: tier must be one of {', '.join(VALID_MODEL_TIERS)}")
    for k in ("extra_gates", "extra_protected_paths"):
        if not all(isinstance(x, str) for x in cfg.get(k, [])):
            errs.append(f"{k} must be a list of strings")
    return errs


def load_config(path=CONFIG_PATH, root=".") -> dict:
    p = Path(root) / path
    if not p.exists():
        raise FileNotFoundError(f"{p} not found; run /laneguard:init first")
    return _merge_defaults(load_file(p))


def protected_paths(cfg: dict) -> list[str]:
    out = list(BASE_PROTECTED_PATHS)
    for extra in cfg.get("extra_protected_paths", []):
        if extra not in out:
            out.append(extra)
    return out


def gates(cfg: dict) -> list[str]:
    return list(BASE_GATES) + [g for g in cfg.get("extra_gates", []) if g not in BASE_GATES]


def path_matches(pattern: str, path: str) -> bool:
    """Match a repo-relative path against a protected-path pattern ('**', '*', trailing '/')."""
    path = path.lstrip("./") if path.startswith("./") else path
    if pattern.endswith("/"):
        pattern = pattern + "**"
    regex = ""
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if pattern[i:i + 3] == "**/":
            regex += "(?:.*/)?"
            i += 3
        elif pattern[i:i + 2] == "**":
            regex += ".*"
            i += 2
        elif c == "*":
            regex += "[^/]*"
            i += 1
        elif c == "?":
            regex += "[^/]"
            i += 1
        else:
            regex += re.escape(c)
            i += 1
    return re.fullmatch(regex, path) is not None


def is_protected(path: str, cfg: dict) -> bool:
    return any(path_matches(p, path) for p in protected_paths(cfg))


def lane_for_label(cfg: dict, label: str):
    for name, lane in cfg.get("lanes", {}).items():
        if lane.get("label") == label:
            return name
    return None


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) >= 2 and argv[0] == "validate":
        try:
            cfg = _merge_defaults(load_file(argv[1]))
        except (YamlError, OSError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        errs = validate(cfg)
        for e in errs:
            print(f"- {e}")
        print("config valid" if not errs else f"{len(errs)} problem(s)")
        return 0 if not errs else 1
    if len(argv) >= 2 and argv[0] == "dump":
        try:
            print(json.dumps(_merge_defaults(load_file(argv[1])), indent=2, sort_keys=True))
        except (YamlError, OSError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        return 0
    print("usage: laneconfig.py validate|dump <config.yaml>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
