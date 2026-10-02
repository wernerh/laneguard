#!/usr/bin/env python3
"""build.py: render a static, self-contained Laneguard status page.

Reads runs.jsonl and PAUSED* flags (from local files, or from the ``laneguard-data`` branch via git)
and writes ONE html file: inline CSS and JS, no external requests. Every value that comes from the
data is untrusted (notes are free text), so it is escaped with html.escape in the markup, and the
JSON copy embedded for the page script has "<", ">", "&" and U+2028/9 escaped. The script never
uses innerHTML; it only sets textContent and toggles ``hidden``.

Python 3, standard library only.

Usage:
  build.py --runs runs.jsonl [--paused-dir DIR] [--config .laneguard/config.yaml] --out site/index.html
  build.py --from-git REMOTE_DIR [--branch laneguard-data] [--config ...] --out site/index.html
"""
from __future__ import annotations

import argparse
import html
import json
import math
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "guard"))
try:  # the guard modules are the source of truth for config parsing and breaker rules
    import laneconfig  # noqa: E402
    import history as _history  # noqa: E402
except ImportError:  # pragma: no cover - dashboard still renders without them
    laneconfig = None
    _history = None

DATA_BRANCH = "laneguard-data"
RUNS_FILE = "runs.jsonl"
PAUSE_PREFIX = "PAUSED"
RECENT = 15
MAX_FILE_BYTES = 20 * 1024 * 1024
FAILING = ("failed", "aborted")
OUTCOMES = ("merged", "pr_opened", "proposed", "quiet", "failed", "aborted", "refused")
TEMPLATE = HERE / "template.html"


class BuildError(RuntimeError):
    pass


# ---------------------------------------------------------------- reading data

def parse_runs(text: str) -> tuple:
    """Return (records, skipped). Bad JSON lines and non-object lines are skipped, never fatal."""
    out, skipped = [], 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            skipped += 1
            continue
        if isinstance(rec, dict):
            out.append(rec)
        else:
            skipped += 1
    return out, skipped


def parse_pause(name: str, text: str) -> tuple:
    lane = name.split(".", 1)[1] if "." in name else "*"
    try:
        body = json.loads(text)
        if not isinstance(body, dict):
            raise ValueError
    except ValueError:
        body = {"reason": text.strip()[:200]}
    return lane or "*", body


def read_pause_dir(path) -> dict:
    out = {}
    d = Path(path)
    if not d.is_dir():
        return out
    for p in sorted(d.iterdir()):
        if p.is_file() and (p.name == PAUSE_PREFIX or p.name.startswith(PAUSE_PREFIX + ".")):
            lane, body = parse_pause(p.name, p.read_text(encoding="utf-8", errors="replace")[:100000])
            out[lane] = body
    return out


def _git(cwd, *args, check=True):
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                       env={**__import__("os").environ, "GIT_TERMINAL_PROMPT": "0"})
    if check and p.returncode != 0:
        raise BuildError(f"git {' '.join(args[:2])} failed: {p.stderr.strip() or p.stdout.strip()}")
    return p


def read_from_git(remote, branch: str = DATA_BRANCH) -> tuple:
    """Return (runs_text, pauses) from the data branch of REMOTE (path or URL). Missing branch = empty."""
    with tempfile.TemporaryDirectory() as tmp:
        _git(tmp, "init", "-q")
        ok = False
        for ref in (f"refs/heads/{branch}", f"refs/remotes/origin/{branch}", branch):
            if _git(tmp, "fetch", "-q", "--no-tags", str(remote), ref, check=False).returncode == 0:
                ok = True
                break
        if not ok:
            return "", {}
        names = _git(tmp, "ls-tree", "--name-only", "FETCH_HEAD").stdout.splitlines()
        runs_text, pauses = "", {}
        for name in names:
            if name != RUNS_FILE and name != PAUSE_PREFIX and not name.startswith(PAUSE_PREFIX + "."):
                continue
            blob = subprocess.run(["git", "-C", tmp, "show", f"FETCH_HEAD:{name}"], capture_output=True)
            if blob.returncode != 0 or len(blob.stdout) > MAX_FILE_BYTES:
                continue
            text = blob.stdout.decode("utf-8", errors="replace")
            if name == RUNS_FILE:
                runs_text = text
            else:
                lane, body = parse_pause(name, text[:100000])
                pauses[lane] = body
        return runs_text, pauses


def load_config(path: Optional[str]) -> dict:
    if not path or laneconfig is None or not Path(path).is_file():
        return {}
    try:
        return laneconfig._merge_defaults(laneconfig.load_file(path))
    except (laneconfig.YamlError, OSError, ValueError):
        return {}


# ---------------------------------------------------------------- model

def _cost(rec) -> float:
    try:
        v = float(rec.get("cost_usd") or 0)
    except (TypeError, ValueError):
        return 0.0
    return v if math.isfinite(v) else 0.0


def _s(v, limit=500) -> str:
    return "" if v is None else str(v)[:limit]


def _month(rec) -> str:
    return _s(rec.get("recorded_at"), 40)[:7]


def breaker_reason(runs: list, lane: str, cfg: dict) -> Optional[str]:
    if _history is not None:
        try:
            return _history.compute_breaker(runs, lane, cfg)
        except Exception:  # malformed data must never break the page
            return None
    return None


def breaker_hint(runs: list, lane: str, cfg: dict) -> dict:
    """Current failure streak against the configured limits, so the page can warn before a trip."""
    b = cfg.get("circuit_breaker") or {"consecutive_failures": 3, "same_pr_failures": 2}
    limit = int(b.get("consecutive_failures", 3) or 0)
    mine = [r for r in runs if r.get("lane") == lane and r.get("outcome") != "refused"]
    streak = 0
    for r in reversed(mine):
        if r.get("outcome") in FAILING:
            streak += 1
        elif r.get("outcome") == "quiet":
            continue
        else:
            break
    return {"streak": streak, "limit": limit, "tripped": breaker_reason(runs, lane, cfg)}


def build_model(runs: list, pauses: dict, cfg: dict, now: datetime, skipped: int = 0) -> dict:
    month = now.strftime("%Y-%m")
    lane_names = list((cfg.get("lanes") or {}).keys())
    for r in runs:
        ln = _s(r.get("lane"), 80) or "(unknown)"
        if ln not in lane_names:
            lane_names.append(ln)
    for ln in pauses:
        if ln != "*" and ln not in lane_names:
            lane_names.append(ln)
    ceiling = 0.0
    try:
        ceiling = float((cfg.get("budgets") or {}).get("monthly_cost_ceiling_usd", 0) or 0)
    except (TypeError, ValueError):
        pass
    if not math.isfinite(ceiling):
        ceiling = 0.0
    indexed = sorted(enumerate(runs), key=lambda t: (_s(t[1].get("recorded_at"), 40), t[0]))
    ordered = [r for _, r in indexed]
    lanes = []
    for ln in lane_names:
        mine = [r for r in ordered if (_s(r.get("lane"), 80) or "(unknown)") == ln]
        counts = {}
        for r in mine:
            o = _s(r.get("outcome"), 40) or "unknown"
            counts[o] = counts.get(o, 0) + 1
        pause = pauses.get(ln) or pauses.get("*")
        latest = mine[-1] if mine else None
        lanes.append({
            "name": ln,
            "latest_outcome": _s(latest.get("outcome"), 40) if latest else "",
            "latest_at": _s(latest.get("recorded_at"), 40) if latest else "",
            "counts": counts,
            "total_runs": len(mine),
            "month_cost_usd": round(sum(_cost(r) for r in mine if _month(r) == month), 6),
            "paused": pause is not None,
            "pause_scope": "all lanes" if (ln not in pauses and "*" in pauses) else "this lane",
            "pause": {k: _s(v, 300) for k, v in (pause or {}).items()},
            "breaker": breaker_hint(ordered, ln, cfg) if ln != "(unknown)" else {"streak": 0, "limit": 0, "tripped": None},
            "recent": [{
                "run_id": _s(r.get("run_id"), 120), "outcome": _s(r.get("outcome"), 40),
                "recorded_at": _s(r.get("recorded_at"), 40), "pr": _s(r.get("pr"), 20),
                "cost_usd": _s(r.get("cost_usd"), 20), "turns": _s(r.get("turns"), 20),
                "tokens": _s(r.get("tokens"), 20), "note": _s(r.get("note"), 500),
            } for r in reversed(mine[-RECENT:])],
        })
    total_month = round(sum(_cost(r) for r in runs if _month(r) == month), 6)
    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "month": month,
        "month_cost_usd": total_month, "ceiling_usd": ceiling,
        "over_ceiling": ceiling > 0 and total_month >= ceiling,
        "total_runs": len(runs), "skipped_lines": skipped, "global_pause": pauses.get("*") is not None,
        "project": _s(cfg.get("project"), 120), "lanes": lanes,
    }


# ---------------------------------------------------------------- rendering

def e(v) -> str:
    return html.escape(str(v), quote=True)


def money(v) -> str:
    return f"${float(v):,.2f}"


def json_for_script(obj) -> str:
    s = json.dumps(obj, sort_keys=True, ensure_ascii=True)
    return s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _badge(outcome: str) -> str:
    if not outcome:
        return '<span class="badge none">no runs</span>'
    cls = outcome if outcome in OUTCOMES else "other"
    return f'<span class="badge {e(cls)}">{e(outcome)}</span>'


def render_lane(lane: dict, ceiling: float, idx: int) -> str:
    hid = f"lane-{idx}"
    parts = [f'<section class="lane" data-lane="{e(lane["name"])}" aria-labelledby="{hid}">']
    parts.append(f'<h2 id="{hid}">{e(lane["name"])}</h2>')
    parts.append('<div class="chips">')
    parts.append(f'<span>Latest: {_badge(lane["latest_outcome"])}'
                 + (f' <time>{e(lane["latest_at"])}</time>' if lane["latest_at"] else "") + "</span>")
    if lane["paused"]:
        why = lane["pause"].get("reason", "")
        parts.append(f'<span class="badge paused" role="status">PAUSED ({e(lane["pause_scope"])})'
                     + (f': {e(why)}' if why else "") + "</span>")
    else:
        parts.append('<span class="badge ok">running</span>')
    parts.append("</div>")
    b = lane["breaker"]
    if b["tripped"]:
        parts.append(f'<p class="warn">Circuit breaker condition met: {e(b["tripped"])}</p>')
    elif b["limit"] and b["streak"]:
        parts.append(f'<p class="hint">Breaker hint: {e(b["streak"])} of {e(b["limit"])} consecutive '
                     "failures before this lane pauses.</p>")
    if lane["counts"]:
        parts.append('<ul class="counts" aria-label="Outcome counts">'
                     + "".join(f'<li>{_badge(k)} <b>{e(v)}</b></li>' for k, v in sorted(lane["counts"].items()))
                     + "</ul>")
    parts.append(f'<p>Cost this month: <b>{e(money(lane["month_cost_usd"]))}</b>'
                 + (f' of {e(money(ceiling))} project ceiling' if ceiling > 0 else "") + "</p>")
    if lane["recent"]:
        parts.append(f'<table><caption>Recent runs (newest first, up to {RECENT})</caption><thead><tr>'
                     '<th scope="col">When</th><th scope="col">Run</th><th scope="col">Outcome</th>'
                     '<th scope="col">PR</th><th scope="col">Cost</th><th scope="col">Turns</th>'
                     '<th scope="col">Note</th></tr></thead><tbody>')
        for r in lane["recent"]:
            parts.append(
                f'<tr><td>{e(r["recorded_at"])}</td><td><code>{e(r["run_id"])}</code></td>'
                f'<td>{_badge(r["outcome"])}</td><td>{e(r["pr"])}</td><td>{e(r["cost_usd"])}</td>'
                f'<td>{e(r["turns"])}</td><td class="note">{e(r["note"])}</td></tr>')
        parts.append("</tbody></table>")
    else:
        parts.append('<p class="empty">No runs recorded for this lane yet.</p>')
    parts.append("</section>")
    return "".join(parts)


def render(model: dict) -> str:
    tpl = TEMPLATE.read_text(encoding="utf-8")
    ceiling = model["ceiling_usd"]
    summary = [f'<p>Month {e(model["month"])}: <b>{e(money(model["month_cost_usd"]))}</b>'
               + (f' of {e(money(ceiling))} ceiling' if ceiling > 0 else " (no ceiling set)")
               + f'. {e(model["total_runs"])} runs recorded.</p>']
    if ceiling > 0:
        summary.append(f'<meter min="0" max="{e(ceiling)}" value="{e(min(model["month_cost_usd"], ceiling))}" '
                       f'aria-label="Monthly cost against ceiling">{e(money(model["month_cost_usd"]))}</meter>')
    if model["over_ceiling"]:
        summary.append('<p class="warn" role="alert">Monthly cost ceiling reached: lanes will not start.</p>')
    if model["global_pause"]:
        summary.append('<p class="warn" role="status">All lanes are paused (PAUSED flag).</p>')
    if model["skipped_lines"]:
        summary.append(f'<p class="hint">{e(model["skipped_lines"])} unreadable line(s) in runs.jsonl were skipped.</p>')
    lanes = "".join(render_lane(l, ceiling, i) for i, l in enumerate(model["lanes"]))
    if not model["lanes"]:
        lanes = '<p class="empty">No lanes or runs found yet.</p>'
    title = "Laneguard dashboard" + (f' - {model["project"]}' if model["project"] else "")
    vals = {"TITLE": e(title), "GENERATED": e(model["generated_at"]), "SUMMARY": "".join(summary),
            "LANES": lanes, "DATA_JSON": json_for_script(model)}
    # single pass: data containing "{{LANES}}" etc. must never be re-substituted
    out = re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: vals.get(m.group(1), m.group(0)), tpl)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="build.py", description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--runs", help="path to runs.jsonl")
    src.add_argument("--from-git", metavar="REMOTE_DIR", help="git repo path or URL holding the data branch")
    ap.add_argument("--branch", default=DATA_BRANCH)
    ap.add_argument("--paused-dir", help="directory holding PAUSED / PAUSED.<lane> files (with --runs)")
    ap.add_argument("--config", help="path to .laneguard/config.yaml (lanes, ceiling, breaker limits)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--now", help="override the clock (ISO 8601, UTC); for tests")
    args = ap.parse_args(argv)
    try:
        if args.from_git:
            text, pauses = read_from_git(args.from_git, args.branch)
        else:
            rp = Path(args.runs)
            text = rp.read_text(encoding="utf-8", errors="replace") if rp.is_file() else ""
            pauses = read_pause_dir(args.paused_dir) if args.paused_dir else {}
        runs, skipped = parse_runs(text)
        now = (datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now
               else datetime.now(timezone.utc))
        page = render(build_model(runs, pauses, load_config(args.config), now, skipped))
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page, encoding="utf-8")
    except (BuildError, OSError, ValueError) as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 2
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
