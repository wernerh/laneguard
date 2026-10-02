import datetime as dt
import io
import json
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lock  # noqa: E402

CONFIG = """project: demo
repo: acme/demo
owners: [alice]
profile: minimal
lanes:
  dev: { label: laneguard, schedule: "every 2h", owns: [PROJECT_STATE.md], mode: propose }
"""


class FakeClock(lock.Clock):
    """A shared 'forge' clock. Tests advance it explicitly; no real time is involved."""

    def __init__(self, start="2026-10-02T12:00:00Z"):
        self._t = lock.parse_ts(start)
        self._lock = threading.Lock()

    def now(self):
        with self._lock:
            return self._t

    def advance(self, minutes):
        with self._lock:
            self._t += dt.timedelta(minutes=minutes)


def git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


class LockTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.remote = self.root / "remote.git"
        git("init", "--bare", "--quiet", str(self.remote))
        self.clock = FakeClock()
        self.clones = []

    def tearDown(self):
        self.tmp.cleanup()

    def clone(self, name):
        d = self.root / name
        git("init", "--quiet", str(d))
        git("remote", "add", "origin", str(self.remote), cwd=d)
        self.clones.append(d)
        return d

    def store(self, name, ttl=45, **kw):
        return lock.LockStore(self.clone(name), clock=self.clock, ttl_minutes=ttl, **kw)


class AcquireReleaseTests(LockTestCase):
    def test_acquire_then_status_then_release(self):
        a = self.store("a")
        r = a.acquire("dev", "run-1")
        self.assertTrue(r.ok, r.detail)
        self.assertEqual(r.action, "acquired")
        st = a.status()
        self.assertTrue(st["held"])
        self.assertEqual(st["holder"], "dev:run-1")
        self.assertFalse(st["stale"])
        self.assertTrue(a.release("dev", "run-1").ok)
        self.assertFalse(a.status()["held"])

    def test_second_acquirer_is_told_to_stop_quietly(self):
        a, b = self.store("a"), self.store("b")
        self.assertTrue(a.acquire("dev", "run-1").ok)
        r = b.acquire("security", "run-2")
        self.assertFalse(r.ok)
        self.assertEqual(r.code, lock.EXIT_HELD)
        self.assertEqual(r.detail["holder"], "dev:run-1")

    def test_acquire_is_idempotent_for_same_run(self):
        a = self.store("a")
        self.assertTrue(a.acquire("dev", "run-1").ok)
        self.clock.advance(5)
        r = a.acquire("dev", "run-1")
        self.assertTrue(r.ok)
        self.assertEqual(r.action, "heartbeat")

    def test_release_by_non_holder_refused(self):
        a, b = self.store("a"), self.store("b")
        a.acquire("dev", "run-1")
        r = b.release("dev", "run-2")
        self.assertFalse(r.ok)
        self.assertEqual(r.code, lock.EXIT_REFUSED)
        self.assertTrue(a.status()["held"])

    def test_release_when_free_is_ok(self):
        self.assertTrue(self.store("a").release("dev", "run-1").ok)

    def test_lock_commit_carries_forge_time_not_local_time(self):
        a = self.store("a")
        a.acquire("dev", "run-1")
        out = subprocess.run(
            ["git", "-C", str(self.remote), "log", "-1", "--format=%cI", lock.LOCK_REF],
            capture_output=True, text=True, check=True).stdout.strip()
        self.assertTrue(out.startswith("2026-10-02T12:00:00"), out)


class RaceTests(LockTestCase):
    def _racers(self, prefix, n):
        """Build n stores that all read the lock, then push one at a time. Every racer has seen
        the same state, so the server-side compare-and-swap is the only thing that can stop the
        later pushes. (Pushing truly simultaneously would let git's own ref locking mask a broken
        CAS, which is why the pushes are serialised here.)"""
        barrier = threading.Barrier(n)
        turn = threading.Lock()

        def before(action):
            barrier.wait(timeout=60)
            turn.acquire()

        def after(action):
            turn.release()

        return [self.store(f"{prefix}{i}", before_push=before, after_push=after) for i in range(n)]

    def _run_all(self, stores, lane_fmt):
        results = [None] * len(stores)

        def go(i):
            results[i] = stores[i].acquire("dev", lane_fmt.format(i))

        threads = [threading.Thread(target=go, args=(i,)) for i in range(len(stores))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results

    def test_n_parallel_acquirers_exactly_one_wins(self):
        n = 8
        stores = self._racers("racer", n)
        results = self._run_all(stores, "run-{}")
        winners = [r for r in results if r.ok]
        self.assertEqual(len(winners), 1, [r.to_dict() for r in results])
        for r in results:
            if not r.ok:
                self.assertEqual(r.code, lock.EXIT_LOST)
        winner_id = next(i for i, r in enumerate(results) if r.ok)
        probe = self.store("probe")
        self.assertEqual(probe.status()["holder"], f"dev:run-{winner_id}")

    def test_n_parallel_takeovers_of_a_stale_lock_exactly_one_wins(self):
        holder = self.store("holder")
        holder.acquire("dev", "old")
        self.clock.advance(46)
        stores = self._racers("taker", 6)
        results = self._run_all(stores, "new-{}")
        self.assertEqual(sum(1 for r in results if r.ok), 1, [r.to_dict() for r in results])
        for r in results:
            if not r.ok:
                self.assertEqual(r.code, lock.EXIT_LOST)


class StaleTests(LockTestCase):
    def test_not_stale_just_inside_ttl(self):
        a, b = self.store("a"), self.store("b")
        a.acquire("dev", "run-1")
        self.clock.advance(44)
        r = b.acquire("security", "run-2")
        self.assertEqual(r.code, lock.EXIT_HELD)

    def test_stale_takeover_is_logged_and_old_holder_loses(self):
        a, b = self.store("a"), self.store("b")
        a.acquire("dev", "crashed")
        self.clock.advance(45)  # no heartbeat for a full TTL: the holder crashed
        r = b.acquire("dev", "run-2")
        self.assertTrue(r.ok, r.detail)
        self.assertEqual(r.action, "takeover")
        self.assertEqual(r.detail["previous"]["holder"], "dev:crashed")
        self.assertEqual(b.status()["takeover_of"]["holder"], "dev:crashed")
        late = a.heartbeat("dev", "crashed")
        self.assertFalse(late.ok)
        self.assertEqual(late.code, lock.EXIT_REFUSED)

    def test_heartbeats_keep_a_long_run_alive(self):
        a, b = self.store("a"), self.store("b")
        a.acquire("dev", "run-1")
        for _ in range(5):
            self.clock.advance(10)
            self.assertTrue(a.heartbeat("dev", "run-1").ok)
        self.assertEqual(b.acquire("security", "run-2").code, lock.EXIT_HELD)

    def test_takeover_loses_cleanly_to_a_late_heartbeat(self):
        a = self.store("a")
        a.acquire("dev", "run-1")
        self.clock.advance(44)  # not stale yet; the taker will see staleness after the next tick
        self.clock.advance(1)

        def heartbeat_just_before_push(action):
            if action == "takeover":
                holder_clock_back = a.clock
                # the holder heartbeats between the taker's read and the taker's push
                a.before_push = None
                saved = a.is_stale
                a.is_stale = lambda info, now: False  # the holder believes it is still alive
                try:
                    self.assertTrue(a.heartbeat("dev", "run-1").ok)
                finally:
                    a.is_stale = saved

        taker = self.store("taker", before_push=heartbeat_just_before_push)
        r = taker.acquire("dev", "run-2")
        self.assertFalse(r.ok)
        self.assertEqual(r.code, lock.EXIT_LOST)
        self.assertEqual(a.status()["holder"], "dev:run-1")

    def test_status_alarm_after_twice_the_ttl(self):
        a = self.store("a")
        a.acquire("dev", "run-1")
        self.clock.advance(89)
        self.assertFalse(a.status()["alarm"])
        self.clock.advance(1)
        self.assertTrue(a.status()["alarm"])

    def test_corrupt_lock_is_never_taken_over(self):
        a = self.store("a")
        a.acquire("dev", "run-1")
        # overwrite the ref with a commit that is not a valid lock payload
        tree = subprocess.run(["git", "-C", str(a.repo_dir), "mktree"], input="", capture_output=True,
                              text=True, check=True).stdout.strip()
        env = {"GIT_AUTHOR_NAME": "x", "GIT_AUTHOR_EMAIL": "x@x", "GIT_COMMITTER_NAME": "x",
               "GIT_COMMITTER_EMAIL": "x@x", "PATH": subprocess.os.environ["PATH"]}
        bad = subprocess.run(["git", "-C", str(a.repo_dir), "commit-tree", tree, "-m", "garbage"],
                             capture_output=True, text=True, check=True, env=env).stdout.strip()
        git("push", "--quiet", "--force", "origin", f"{bad}:{lock.LOCK_REF}", cwd=a.repo_dir)
        self.clock.advance(500)
        b = self.store("b")
        r = b.acquire("dev", "run-2")
        self.assertFalse(r.ok)
        self.assertEqual(r.code, lock.EXIT_HELD)
        self.assertTrue(r.detail.get("corrupt"))
        self.assertTrue(b.status()["alarm"])


class ClockSkewTests(LockTestCase):
    def test_no_wall_clock_is_read_by_lock_py(self):
        src = (Path(lock.__file__)).read_text()
        for needle in ("datetime.now(", ".utcnow(", "time.time(", "time.monotonic(", "date.today(", "perf_counter("):
            self.assertNotIn(needle, src, f"lock.py must not read a local clock ({needle})")

    def test_two_runs_with_wildly_different_local_clocks_agree(self):
        # Both runs read the same forge clock; local machine time cannot influence staleness.
        a, b = self.store("a"), self.store("b")
        a.acquire("dev", "run-1")
        self.clock.advance(10)
        self.assertEqual(b.acquire("security", "run-2").code, lock.EXIT_HELD)


class CliTests(LockTestCase):
    def run_cli(self, *argv):
        d = self.root / "cli"
        if not d.exists():
            git("init", "--quiet", str(d))
            git("remote", "add", "origin", str(self.remote), cwd=d)
            (d / ".laneguard").mkdir()
            (d / ".laneguard" / "config.yaml").write_text(CONFIG)
        buf = io.StringIO()
        code = lock.main(["--repo-dir", str(d), "--config", str(d / ".laneguard" / "config.yaml"), *argv],
                         clock=self.clock, out=buf)
        return code, json.loads(buf.getvalue())

    def test_cli_round_trip_and_exit_codes(self):
        code, out = self.run_cli("status")
        self.assertEqual((code, out["held"]), (0, False))
        code, out = self.run_cli("acquire", "--lane", "dev", "--run-id", "r1")
        self.assertEqual((code, out["action"]), (0, "acquired"))
        code, out = self.run_cli("acquire", "--lane", "dev", "--run-id", "r2")
        self.assertEqual((code, out["action"]), (lock.EXIT_HELD, "held"))
        code, out = self.run_cli("release", "--lane", "dev", "--run-id", "r2")
        self.assertEqual(code, lock.EXIT_REFUSED)
        code, out = self.run_cli("release", "--lane", "dev", "--run-id", "r1")
        self.assertEqual((code, out["action"]), (0, "released"))

    def test_cli_missing_config_is_an_error_exit(self):
        buf = io.StringIO()
        code = lock.main(["--config", str(self.root / "nope.yaml"), "status"], clock=self.clock, out=buf)
        self.assertEqual(code, lock.EXIT_ERROR)
        self.assertFalse(json.loads(buf.getvalue())["ok"])

    def test_ttl_comes_from_config(self):
        d = self.root / "cfg"
        d.mkdir()
        (d / "c.yaml").write_text(CONFIG.replace("lanes:", "limits: {lock_ttl_minutes: 60, run_max_minutes: 30}\nlanes:"))
        self.assertEqual(lock._ttl_from_config(str(d / "c.yaml")), 60)


if __name__ == "__main__":
    unittest.main()
