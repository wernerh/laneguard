#!/usr/bin/env python3
"""history.py: run history, pause flags, circuit breaker and cost ceiling, all on ``laneguard-data``.

Why a separate branch: lane-writable files on the default branch would make every run a
protected-path edit. ``laneguard-data`` is an orphan branch that holds only ``runs.jsonl`` and
``PAUSED*`` flags. It is never merged anywhere. Protect it so only owners can delete files
there (see docs/setup/branch-protection.md); ``unpause`` also checks the caller is an owner.

Records are append-only JSON lines. Timestamps come from the forge's clock (never the local
clock), values are scrubbed for secrets and environment variable values before writing, and
concurrent writers are handled by fetch, re-apply, push, retry.

The circuit breaker is computed from history on every ``status``/``pause-check``, so there is no
counter a lane could reset: N consecutive failures in a lane, or M failures on the same PR,
pause that lane. A pause is a ``PAUSED.<lane>`` file; ``PAUSED`` pauses everything.

Python 3, standard library only.

Usage:
  history.py record   --lane L --run-id ID --outcome O [--pr N] [--cost-usd X] [--turns N] [--tokens N] [--note T]
  history.py status   [--lane L] [--json]       summary, breaker and cost state; trips the breaker if due
  history.py pause    [--lane L] --reason T     pause one lane (or all without --lane)
  history.py unpause  [--lane L]                owners only
  history.py pause-check --lane L               exit 0 clear, 3 paused or over ceiling
  history.py list     [--lane L] [--limit N]

Outcomes: merged, pr_opened, proposed, quiet, failed, aborted, refused.
Exit codes: 0 ok; 1 refused; 2 usage or environment error; 3 paused / ceiling reached.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import laneconfig  # noqa: E402

DATA_BRANCH = "laneguard-data"
RUNS_FILE = "runs.jsonl"
PAUSE_PREFIX = "PAUSED"
OUTCOMES = ("merged", "pr_opened", "proposed", "quiet", "failed", "aborted", "refused")
FAILING = ("failed", "aborted")
MAX_NOTE = 500
MAX_RETRIES = 6

SECRET_RES = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"), re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{20,}"),
]
SENSITIVE_ENV = re.compile(r"(?i)(token|secret|password|passwd|api[_-]?key|private|credential)")


class HistoryError(RuntimeError):
    pass


class Denied(HistoryError):
    pass


def scrub(text: str, environ=None) -> str:
    """Remove secret-shaped strings and the values of sensitive environment variables."""
    text = str(text)
    for name, val in (os.environ if environ is None else environ).items():
        if SENSITIVE_ENV.search(name) and val and len(val) >= 8:
            text = text.replace(val, "[redacted]")
    for rx in SECRET_RES:
        text = rx.sub("[redacted]", text)
    return text


def month_of(ts: str) -> str:
    return ts[:7]


def compute_breaker(runs: list, lane: str, cfg: dict) -> Optional[str]:
    """Return a reason string if history says this lane must pause, else None."""
    b = cfg.get("circuit_breaker") or {}
    consecutive = int(b.get("consecutive_failures", 3))
    same_pr = int(b.get("same_pr_failures", 2))
    mine = [r for r in runs if r.get("lane") == lane and r.get("outcome") != "refused"]
    streak = 0
    for r in reversed(mine):
        if r.get("outcome") in FAILING:
            streak += 1
        elif r.get("outcome") == "quiet":
            continue
        else:
            break
    if consecutive > 0 and streak >= consecutive:
        return f"{streak} consecutive failed runs in lane {lane}"
    counts: dict = {}
    for r in mine:
        pr = r.get("pr")
        if pr is None:
            continue
        if r.get("outcome") in FAILING:
            counts[pr] = counts.get(pr, 0) + 1
        elif r.get("outcome") in ("merged",):
            counts[pr] = 0
    for pr, n in counts.items():
        if same_pr > 0 and n >= same_pr:
            return f"{n} failed runs on PR #{pr} in lane {lane}"
    return None


def month_cost(runs: list, month: str) -> float:
    total = 0.0
    for r in runs:
        if month_of(str(r.get("recorded_at", ""))) == month:
            try:
                total += float(r.get("cost_usd") or 0)
            except (TypeError, ValueError):
                pass
    return round(total, 6)


class DataBranch:
    """Transactional access to the ``laneguard-data`` branch through a throwaway clone."""

    def __init__(self, repo_dir=".", remote="origin", branch=DATA_BRANCH):
        self.repo_dir, self.remote, self.branch = str(repo_dir), remote, branch

    def _git(self, cwd, *args, check=True):
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
        p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=env)
        if check and p.returncode != 0:
            raise HistoryError(f"git {' '.join(args[:2])} failed: {p.stderr.strip() or p.stdout.strip()}")
        return p

    def _remote_url(self) -> str:
        p = subprocess.run(["git", "-C", self.repo_dir, "remote", "get-url", self.remote],
                           capture_output=True, text=True)
        if p.returncode != 0:
            raise HistoryError(f"no git remote named {self.remote!r}")
        return p.stdout.strip()

    def _open(self, tmp: str) -> bool:
        """Prepare a work tree at the remote branch tip. Returns True if the branch exists."""
        self._git(tmp, "init", "-q")
        self._git(tmp, "config", "user.name", "laneguard")
        self._git(tmp, "config", "user.email", "laneguard@users.noreply.github.com")
        self._git(tmp, "config", "commit.gpgsign", "false")
        self._git(tmp, "remote", "add", "origin", self._remote_url())
        ls = self._git(tmp, "ls-remote", "--heads", "origin", self.branch)
        if ls.stdout.strip():
            self._git(tmp, "fetch", "-q", "origin", self.branch)
            self._git(tmp, "checkout", "-q", "-B", self.branch, "FETCH_HEAD")
            return True
        self._git(tmp, "checkout", "-q", "--orphan", self.branch)
        return False

    def read(self) -> dict:
        """Return {filename: text} for the branch (empty if it does not exist yet)."""
        with tempfile.TemporaryDirectory() as tmp:
            if not self._open(tmp):
                return {}
            return {p.name: p.read_text(encoding="utf-8") for p in Path(tmp).iterdir() if p.is_file()}

    def transact(self, fn: Callable[[Path], bool], message: str) -> bool:
        """Run fn(workdir) against the branch tip and push. fn returns False for 'nothing to do'.
        Retries from a fresh fetch when another writer got there first."""
        last = ""
        for _ in range(MAX_RETRIES):
            with tempfile.TemporaryDirectory() as tmp:
                self._open(tmp)
                work = Path(tmp)
                if fn(work) is False:
                    return False
                self._git(tmp, "add", "-A")
                self._git(tmp, "commit", "-q", "-m", message)
                p = self._git(tmp, "push", "-q", "origin", f"HEAD:refs/heads/{self.branch}", check=False)
                if p.returncode == 0:
                    return True
                last = p.stderr.strip()
        raise HistoryError(f"could not update {self.branch} after {MAX_RETRIES} attempts: {last}")


class History:
    def __init__(self, data: DataBranch, cfg: dict, clock=None, forge=None):
        self.data, self.cfg, self.clock, self.forge = data, cfg, clock, forge

    def _now(self) -> str:
        if self.clock is None:
            import forge as forge_mod
            self.clock = forge_mod.from_config()
        from lock import fmt
        return fmt(self.clock.now())

    # ---- reading

    def runs(self) -> list:
        text = self.data.read().get(RUNS_FILE, "")
        out = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                out.append({"outcome": "corrupt-line"})
        return out

    def pauses(self) -> dict:
        files = self.data.read()
        out = {}
        for name, text in files.items():
            if name == PAUSE_PREFIX or name.startswith(PAUSE_PREFIX + "."):
                lane = name.split(".", 1)[1] if "." in name else "*"
                try:
                    out[lane] = json.loads(text)
                except ValueError:
                    out[lane] = {"reason": text.strip()[:200]}
        return out

    # ---- writing

    def record(self, lane, run_id, outcome, pr=None, cost_usd=None, turns=None, tokens=None, note="") -> dict:
        if outcome not in OUTCOMES:
            raise HistoryError(f"outcome must be one of {', '.join(OUTCOMES)}")
        if lane not in self.cfg.get("lanes", {}):
            raise HistoryError(f"unknown lane {lane!r}")
        rec = {"run_id": scrub(run_id)[:80], "lane": lane, "outcome": outcome, "recorded_at": self._now()}
        if pr is not None:
            rec["pr"] = int(pr)
        for k, v in (("cost_usd", cost_usd), ("turns", turns), ("tokens", tokens)):
            if v is not None:
                rec[k] = float(v) if k == "cost_usd" else int(v)
        if note:
            rec["note"] = scrub(note)[:MAX_NOTE]
        line = json.dumps(rec, sort_keys=True, separators=(",", ":"))

        def add(work: Path):
            f = work / RUNS_FILE
            old = f.read_text(encoding="utf-8") if f.exists() else ""
            if old and not old.endswith("\n"):
                old += "\n"
            f.write_text(old + line + "\n", encoding="utf-8")
            return True

        self.data.transact(add, f"run {rec['run_id']} {lane} {outcome}")
        return rec

    def pause(self, lane: Optional[str], reason: str, by: str = "") -> dict:
        if lane is not None and lane not in self.cfg.get("lanes", {}):
            raise HistoryError(f"unknown lane {lane!r}")
        name = PAUSE_PREFIX if lane is None else f"{PAUSE_PREFIX}.{lane}"
        body = {"reason": scrub(reason)[:MAX_NOTE], "by": scrub(by)[:80], "at": self._now()}

        def put(work: Path):
            f = work / name
            if f.exists():
                return False
            f.write_text(json.dumps(body, sort_keys=True) + "\n", encoding="utf-8")
            return True

        self.data.transact(put, f"pause {lane or 'all'}")
        return {"paused": lane or "*", **body}

    def unpause(self, lane: Optional[str]) -> dict:
        f = self.forge
        if f is None:
            import forge as forge_mod
            f = self.forge = forge_mod.from_config()
        login = f.whoami()
        if not login or not f.is_owner(login):
            raise Denied("only a configured owner (a person, never a bot) may unpause")
        name = PAUSE_PREFIX if lane is None else f"{PAUSE_PREFIX}.{lane}"

        def rm(work: Path):
            p = work / name
            if not p.exists():
                return False
            p.unlink()
            return True

        removed = self.data.transact(rm, f"unpause {lane or 'all'} by {login}")
        return {"unpaused": lane or "*", "removed": removed, "by": login}

    # ---- decisions

    def evaluate(self, lane: str, trip: bool = True) -> dict:
        runs = self.runs()
        pauses = self.pauses()
        reason = compute_breaker(runs, lane, self.cfg)
        paused_by = None
        if "*" in pauses:
            paused_by = pauses["*"]
        elif lane in pauses:
            paused_by = pauses[lane]
        if reason and paused_by is None and trip:
            paused_by = self.pause(lane, f"circuit breaker: {reason}", by="laneguard")
        ceiling = float(self.cfg["budgets"].get("monthly_cost_ceiling_usd", 0) or 0)
        spent = month_cost(runs, month_of(self._now()))
        over = ceiling > 0 and spent >= ceiling
        return {
            "lane": lane, "paused": paused_by is not None, "pause": paused_by,
            "breaker": reason, "month_cost_usd": spent, "ceiling_usd": ceiling,
            "over_ceiling": over, "runs_recorded": len(runs),
            "may_run": paused_by is None and not over,
        }


def load_cfg(path: Optional[str]) -> dict:
    p = Path(path or laneconfig.CONFIG_PATH)
    return laneconfig._merge_defaults(laneconfig.load_file(p))


def main(argv=None, history: Optional[History] = None, out=None) -> int:
    out = out or sys.stdout
    ap = argparse.ArgumentParser(prog="history.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--config")
    ap.add_argument("--repo-dir", default=".")
    ap.add_argument("--remote", default="origin")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--lane", required=True); r.add_argument("--run-id", required=True)
    r.add_argument("--outcome", required=True, choices=OUTCOMES); r.add_argument("--pr", type=int)
    r.add_argument("--cost-usd", type=float); r.add_argument("--turns", type=int)
    r.add_argument("--tokens", type=int); r.add_argument("--note", default="")
    s = sub.add_parser("status"); s.add_argument("--lane"); s.add_argument("--json", action="store_true")
    s.add_argument("--no-trip", action="store_true")
    p = sub.add_parser("pause"); p.add_argument("--lane"); p.add_argument("--reason", required=True); p.add_argument("--by", default="")
    u = sub.add_parser("unpause"); u.add_argument("--lane")
    c = sub.add_parser("pause-check"); c.add_argument("--lane", required=True)
    ls = sub.add_parser("list"); ls.add_argument("--lane"); ls.add_argument("--limit", type=int, default=20)
    args = ap.parse_args(argv)
    try:
        h = history or History(DataBranch(args.repo_dir, args.remote), load_cfg(args.config))
        if args.cmd == "record":
            print(json.dumps(h.record(args.lane, args.run_id, args.outcome, args.pr, args.cost_usd,
                                      args.turns, args.tokens, args.note)), file=out)
            return 0
        if args.cmd == "pause":
            print(json.dumps(h.pause(args.lane, args.reason, args.by)), file=out)
            return 0
        if args.cmd == "unpause":
            print(json.dumps(h.unpause(args.lane)), file=out)
            return 0
        if args.cmd == "list":
            rows = [x for x in h.runs() if not args.lane or x.get("lane") == args.lane]
            for row in rows[-args.limit:]:
                print(json.dumps(row, sort_keys=True), file=out)
            return 0
        lanes = [args.lane] if getattr(args, "lane", None) else list(h.cfg["lanes"])
        results = [h.evaluate(l, trip=(args.cmd == "pause-check") or not getattr(args, "no_trip", False)) for l in lanes]
        if args.cmd == "pause-check":
            res = results[0]
            print(json.dumps(res, sort_keys=True), file=out)
            return 0 if res["may_run"] else 3
        if args.json:
            print(json.dumps(results, indent=2, sort_keys=True), file=out)
        else:
            for res in results:
                state = "PAUSED" if res["paused"] else "over ceiling" if res["over_ceiling"] else "ok"
                print(f"{res['lane']}: {state}  month ${res['month_cost_usd']:.2f}/${res['ceiling_usd']:.0f}"
                      + (f"  breaker: {res['breaker']}" if res["breaker"] else ""), file=out)
        return 0
    except Denied as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    except (HistoryError, FileNotFoundError, laneconfig.YamlError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
