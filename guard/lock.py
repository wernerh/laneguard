#!/usr/bin/env python3
"""lock.py: the only code allowed to touch the Laneguard lock.

The lock is the git ref ``refs/laneguard/lock``. Every change is a compare-and-swap done by the
git server: pushes carry an explicit expected old value (``--force-with-lease=<ref>:<sha>``; create
uses an empty expectation, meaning "the ref must not exist"). Two racing runs therefore cannot both
win, because the server refuses the second update.

Time never comes from the local clock or from a model. It comes from the forge (the Date header of
a GitHub API response) through an injected clock object. This module deliberately does not call any
wall-clock function; ``test_lock.py`` asserts that by scanning this file's source.

Python 3, standard library only.

Usage:
  lock.py status   [--json]
  lock.py acquire   --lane LANE --run-id ID
  lock.py heartbeat --lane LANE --run-id ID
  lock.py release   --lane LANE --run-id ID

Exit codes: 0 ok; 1 refused (not the holder); 2 usage, config or clock error;
            3 held by another run and not stale (stop quietly); 4 lost a race (back off).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import laneconfig  # noqa: E402

LOCK_REF = "refs/laneguard/lock"
REMOTE_TRACK_REF = "refs/laneguard/_seen-lock"
EXIT_OK, EXIT_REFUSED, EXIT_ERROR, EXIT_HELD, EXIT_LOST = 0, 1, 2, 3, 4
ISO = "%Y-%m-%dT%H:%M:%SZ"


class LockError(RuntimeError):
    """Operational failure (git, config or clock). Always fails closed."""


class Clock:
    """Source of server time. Implementations must not read the local wall clock."""

    def now(self) -> dt.datetime:  # pragma: no cover - interface
        raise NotImplementedError


class ForgeClock(Clock):
    """Server time taken from the forge's API response (see forge.py)."""

    def __init__(self, forge=None):
        self._forge = forge

    def now(self) -> dt.datetime:
        if self._forge is None:
            import forge  # local import keeps lock.py importable without gh present

            self._forge = forge.from_config()
        return self._forge.now()


def with_token(url: str, token: Optional[str]) -> str:
    """Rewrite an ``https://github.com/...`` remote URL to carry TOKEN as an x-access-token credential.

    Anything else (ssh URLs, other hosts, a URL that already carries credentials, an empty token) is returned
    unchanged. Used only for the read-only ``ls-remote`` so a checkout made with ``persist-credentials: false``
    (the guard workflow) can still read the lock on a private repository.
    """
    prefix = "https://github.com/"
    if not token or not url.startswith(prefix):
        return url
    return f"https://x-access-token:{token}@github.com/" + url[len(prefix):]


def fmt(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime(ISO)


def parse_ts(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, ISO).replace(tzinfo=dt.timezone.utc)


@dataclass
class LockInfo:
    sha: str
    lane: str = ""
    run_id: str = ""
    holder: str = ""
    acquired_at: Optional[dt.datetime] = None
    heartbeat_at: Optional[dt.datetime] = None
    expires_at: Optional[dt.datetime] = None
    takeover_of: Optional[dict] = None
    corrupt: bool = False

    def to_dict(self) -> dict:
        return {
            "sha": self.sha, "lane": self.lane, "run_id": self.run_id, "holder": self.holder,
            "acquired_at": fmt(self.acquired_at) if self.acquired_at else None,
            "heartbeat_at": fmt(self.heartbeat_at) if self.heartbeat_at else None,
            "expires_at": fmt(self.expires_at) if self.expires_at else None,
            "takeover_of": self.takeover_of, "corrupt": self.corrupt,
        }


@dataclass
class Result:
    ok: bool
    code: int
    action: str
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {"ok": self.ok, "action": self.action}
        d.update(self.detail)
        return d


class LockStore:
    def __init__(
        self,
        repo_dir=".",
        remote: str = "origin",
        clock: Optional[Clock] = None,
        ttl_minutes: int = 45,
        ref: str = LOCK_REF,
        before_push: Optional[Callable[[str], None]] = None,
        after_push: Optional[Callable[[str], None]] = None,
    ):
        self.repo_dir = str(repo_dir)
        self.remote = remote
        self.clock = clock if clock is not None else ForgeClock()
        self.ttl = dt.timedelta(minutes=ttl_minutes)
        self.ref = ref
        self.before_push = before_push  # test hooks: called with the action name around each push
        self.after_push = after_push

    # ------------------------------------------------------------------ git plumbing

    def _git(self, *args, env=None, check=True, input_text=None):
        full_env = dict(os.environ)
        full_env["GIT_TERMINAL_PROMPT"] = "0"
        if env:
            full_env.update(env)
        p = subprocess.run(
            ["git", "-C", self.repo_dir, *args], capture_output=True, text=True, env=full_env, input=input_text
        )
        if check and p.returncode != 0:
            raise LockError(f"git {' '.join(args[:2])} failed: {p.stderr.strip() or p.stdout.strip()}")
        return p

    def _ls_remote_target(self) -> str:
        """The remote to query: its URL with GH_TOKEN applied when that helps, otherwise the remote name as given."""
        token = os.environ.get("GH_TOKEN")
        if not token:
            return self.remote
        url = self.remote
        if "://" not in url and ":" not in url:  # a remote name, not a URL
            p = self._git("remote", "get-url", self.remote, check=False)
            if p.returncode != 0:
                return self.remote
            url = p.stdout.strip()
        tokenised = with_token(url, token)
        return tokenised if tokenised != url else self.remote

    def _remote_sha(self) -> Optional[str]:
        # check=False and a hand-built error: the target may carry a token that must never reach a message
        p = self._git("ls-remote", self._ls_remote_target(), self.ref, check=False)
        if p.returncode != 0:
            raise LockError(f"git ls-remote {self.remote} failed: {p.stderr.strip() or p.stdout.strip()}")
        for line in p.stdout.splitlines():
            sha, _, name = line.partition("\t")
            if name.strip() == self.ref:
                return sha.strip()
        return None

    def _parse_commit(self, sha: str) -> LockInfo:
        body = self._git("cat-file", "commit", sha).stdout
        _, _, message = body.partition("\n\n")
        # message: first line is a title, JSON payload follows
        payload = message.split("\n", 1)[1] if "\n" in message else message
        try:
            d = json.loads(payload.strip())
            return LockInfo(
                sha=sha, lane=str(d["lane"]), run_id=str(d["run_id"]), holder=str(d.get("holder", "")),
                acquired_at=parse_ts(d["acquired_at"]), heartbeat_at=parse_ts(d["heartbeat_at"]),
                expires_at=parse_ts(d["expires_at"]), takeover_of=d.get("takeover_of"),
            )
        except (ValueError, KeyError, TypeError):
            return LockInfo(sha=sha, corrupt=True)

    def read(self) -> Optional[LockInfo]:
        sha = self._remote_sha()
        if sha is None:
            return None
        have = self._git("cat-file", "-e", f"{sha}^{{commit}}", check=False)
        if have.returncode != 0:
            self._git("fetch", "--quiet", "--no-tags", self.remote, f"+{self.ref}:{REMOTE_TRACK_REF}")
        return self._parse_commit(sha)

    def _make_commit(self, payload: dict, now: dt.datetime, parent: Optional[str]) -> str:
        tree = self._git("mktree", input_text="").stdout.strip()
        stamp = fmt(now)
        env = {
            "GIT_AUTHOR_NAME": "laneguard-lock", "GIT_AUTHOR_EMAIL": "lock@laneguard.invalid",
            "GIT_COMMITTER_NAME": "laneguard-lock", "GIT_COMMITTER_EMAIL": "lock@laneguard.invalid",
            "GIT_AUTHOR_DATE": f"{stamp} +0000", "GIT_COMMITTER_DATE": f"{stamp} +0000",
        }
        args = ["commit-tree", tree]
        if parent:
            args += ["-p", parent]
        message = "laneguard lock\n" + json.dumps(payload, sort_keys=True, separators=(",", ":"))
        args += ["-m", message]
        return self._git(*args, env=env).stdout.strip()

    def _cas_push(self, commit: str, expect: Optional[str], action: str) -> bool:
        """Push ``commit`` to the lock ref, succeeding only if the ref still equals ``expect``."""
        if self.before_push:
            self.before_push(action)
        try:
            lease = f"--force-with-lease={self.ref}:{expect or ''}"
            p = self._git("push", "--quiet", lease, self.remote, f"{commit}:{self.ref}", check=False)
            return p.returncode == 0
        finally:
            if self.after_push:
                self.after_push(action)

    def _cas_delete(self, expect: str) -> bool:
        if self.before_push:
            self.before_push("release")
        try:
            lease = f"--force-with-lease={self.ref}:{expect}"
            p = self._git("push", "--quiet", lease, self.remote, f":{self.ref}", check=False)
            return p.returncode == 0
        finally:
            if self.after_push:
                self.after_push("release")

    # ------------------------------------------------------------------ queries

    def _holder_id(self, lane: str, run_id: str) -> str:
        return f"{lane}:{run_id}"

    def is_stale(self, info: LockInfo, now: dt.datetime) -> bool:
        if info.corrupt or info.heartbeat_at is None:
            return False  # fail closed: a corrupt lock is never taken over automatically
        return now - info.heartbeat_at >= self.ttl

    def status(self) -> dict:
        now = self.clock.now()
        info = self.read()
        if info is None:
            return {"held": False, "now": fmt(now)}
        d = info.to_dict()
        d["held"] = True
        d["now"] = fmt(now)
        if info.corrupt:
            d["stale"] = False
            d["alarm"] = True
            return d
        age = now - info.heartbeat_at
        d["age_minutes"] = round(age.total_seconds() / 60, 1)
        d["stale"] = self.is_stale(info, now)
        d["alarm"] = age >= 2 * self.ttl
        return d

    # ------------------------------------------------------------------ mutations

    def acquire(self, lane: str, run_id: str) -> Result:
        now = self.clock.now()
        holder = self._holder_id(lane, run_id)
        info = self.read()
        payload = {
            "lane": lane, "run_id": run_id, "holder": holder, "acquired_at": fmt(now),
            "heartbeat_at": fmt(now), "expires_at": fmt(now + self.ttl),
        }
        if info is None:
            commit = self._make_commit(payload, now, parent=None)
            if self._cas_push(commit, None, "acquire"):
                return Result(True, EXIT_OK, "acquired", {"lock": holder, "sha": commit})
            return Result(False, EXIT_LOST, "lost_race", {"reason": "another run created the lock first"})
        if info.corrupt:
            return Result(False, EXIT_HELD, "held", {
                "reason": "lock ref is not a valid Laneguard lock; an owner must inspect it", "corrupt": True})
        if info.holder == holder:
            return self.heartbeat(lane, run_id)
        if not self.is_stale(info, now):
            return Result(False, EXIT_HELD, "held", {
                "reason": "lock is held and not stale", "holder": info.holder, "lane": info.lane,
                "heartbeat_at": fmt(info.heartbeat_at), "expires_at": fmt(info.heartbeat_at + self.ttl)})
        # stale: take over by compare-and-swap against the exact stale commit
        payload["takeover_of"] = {
            "sha": info.sha, "holder": info.holder, "heartbeat_at": fmt(info.heartbeat_at)}
        commit = self._make_commit(payload, now, parent=info.sha)
        if self._cas_push(commit, info.sha, "takeover"):
            return Result(True, EXIT_OK, "takeover", {
                "lock": holder, "sha": commit, "previous": payload["takeover_of"]})
        return Result(False, EXIT_LOST, "lost_race", {
            "reason": "the holder heartbeated or another run took over first; back off"})

    def heartbeat(self, lane: str, run_id: str) -> Result:
        now = self.clock.now()
        holder = self._holder_id(lane, run_id)
        info = self.read()
        if info is None:
            return Result(False, EXIT_REFUSED, "no_lock", {"reason": "no lock is held"})
        if info.corrupt or info.holder != holder:
            return Result(False, EXIT_REFUSED, "not_holder", {
                "reason": "this run does not hold the lock", "holder": info.holder})
        if self.is_stale(info, now):
            # Our own lock went stale before we beat. Someone else may already be taking it over.
            return Result(False, EXIT_REFUSED, "expired", {
                "reason": "lock went stale before the heartbeat; stop and release nothing"})
        payload = {
            "lane": lane, "run_id": run_id, "holder": holder,
            "acquired_at": fmt(info.acquired_at), "heartbeat_at": fmt(now), "expires_at": fmt(now + self.ttl),
        }
        if info.takeover_of:
            payload["takeover_of"] = info.takeover_of
        commit = self._make_commit(payload, now, parent=info.sha)
        if self._cas_push(commit, info.sha, "heartbeat"):
            return Result(True, EXIT_OK, "heartbeat", {"lock": holder, "sha": commit})
        return Result(False, EXIT_LOST, "lost_race", {"reason": "the lock changed under this run; stop"})

    def release(self, lane: str, run_id: str) -> Result:
        holder = self._holder_id(lane, run_id)
        info = self.read()
        if info is None:
            return Result(True, EXIT_OK, "already_free", {})
        if info.corrupt or info.holder != holder:
            return Result(False, EXIT_REFUSED, "not_holder", {
                "reason": "this run does not hold the lock", "holder": info.holder})
        if self._cas_delete(info.sha):
            return Result(True, EXIT_OK, "released", {"lock": holder})
        return Result(False, EXIT_LOST, "lost_race", {"reason": "the lock changed during release"})


def _ttl_from_config(config_path: Optional[str]) -> int:
    path = config_path or laneconfig.CONFIG_PATH
    try:
        cfg = laneconfig.load_config(path)
    except (FileNotFoundError, laneconfig.YamlError) as e:
        raise LockError(str(e))
    problems = laneconfig.validate(cfg)
    if problems:
        raise LockError("invalid config: " + "; ".join(problems))
    return int(cfg["limits"]["lock_ttl_minutes"])


def main(argv=None, clock: Optional[Clock] = None, out=None) -> int:
    out = out or sys.stdout
    ap = argparse.ArgumentParser(prog="lock.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--config", default=None, help="path to config.yaml (default .laneguard/config.yaml)")
    ap.add_argument("--repo-dir", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    for name in ("acquire", "heartbeat", "release"):
        sp = sub.add_parser(name)
        sp.add_argument("--lane", required=True)
        sp.add_argument("--run-id", required=True)
    args = ap.parse_args(argv)
    try:
        ttl = _ttl_from_config(args.config)
        store = LockStore(args.repo_dir, args.remote, clock=clock, ttl_minutes=ttl)
        if args.cmd == "status":
            print(json.dumps(store.status(), sort_keys=True), file=out)
            return EXIT_OK
        res = getattr(store, args.cmd)(args.lane, args.run_id)
    except LockError as e:
        print(json.dumps({"ok": False, "action": "error", "error": str(e)}), file=out)
        return EXIT_ERROR
    print(json.dumps(res.to_dict(), sort_keys=True), file=out)
    return res.code


if __name__ == "__main__":
    sys.exit(main())
