import datetime as dt
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import history as hs  # noqa: E402
import laneconfig as lc  # noqa: E402

CONFIG = """project: demo
repo: acme/demo
owners: [alice]
mode: propose
lanes:
  dev: { label: laneguard, schedule: "every 2h", owns: [PROJECT_STATE.md], mode: propose }
  security: { label: laneguard-security, schedule: "every 4h", owns: [docs/security/], mode: propose }
budgets:
  monthly_cost_ceiling_usd: 10
"""


class FixedClock:
    def __init__(self, t="2026-10-02T10:00:00Z"):
        self.t = dt.datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)

    def now(self):
        return self.t


class FakeForge:
    def __init__(self, login, owner):
        self.login, self.owner = login, owner

    def whoami(self):
        return self.login

    def is_owner(self, login):
        return self.owner


class Base(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        root = Path(self._t.name)
        self.remote = root / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)], check=True)
        self.work = root / "work"
        subprocess.run(["git", "init", "-q", str(self.work)], check=True)
        subprocess.run(["git", "-C", str(self.work), "remote", "add", "origin", str(self.remote)], check=True)
        self.cfg = lc._merge_defaults(lc.loads(CONFIG))
        self.clock = FixedClock()

    def tearDown(self):
        self._t.cleanup()

    def hist(self, forge=None):
        return hs.History(hs.DataBranch(self.work), self.cfg, clock=self.clock, forge=forge)

    def rec(self, h, lane="dev", outcome="failed", **kw):
        kw.setdefault("run_id", f"r{len(h.runs()) + 1}")
        return h.record(lane, kw.pop("run_id"), outcome, **kw)


class ScrubTests(unittest.TestCase):
    def test_secret_shapes_and_env_values_are_redacted(self):
        t = hs.scrub("token ghp_" + "a" * 30 + " and hunter2hunter2 here", environ={"MY_API_KEY": "hunter2hunter2"})
        self.assertNotIn("ghp_", t)
        self.assertNotIn("hunter2", t)
        self.assertIn("[redacted]", t)

    def test_short_env_values_not_over_redacted(self):
        self.assertEqual(hs.scrub("abc", environ={"X_TOKEN": "abc"}), "abc")


class BreakerTests(unittest.TestCase):
    cfg = {"circuit_breaker": {"consecutive_failures": 3, "same_pr_failures": 2}}

    def r(self, *outs, pr=None):
        return [{"lane": "dev", "outcome": o, **({"pr": pr} if pr else {})} for o in outs]

    def test_consecutive_failures_trip(self):
        self.assertIn("3 consecutive", hs.compute_breaker(self.r("failed", "aborted", "failed"), "dev", self.cfg))

    def test_success_resets_streak_and_quiet_is_transparent(self):
        self.assertIsNone(hs.compute_breaker(self.r("failed", "failed", "merged", "failed"), "dev", self.cfg))
        self.assertIsNotNone(hs.compute_breaker(self.r("failed", "quiet", "failed", "quiet", "failed"), "dev", self.cfg))

    def test_same_pr_failures_trip_but_other_prs_do_not(self):
        runs = self.r("failed", pr=7) + self.r("pr_opened") + self.r("failed", pr=7)
        self.assertIn("PR #7", hs.compute_breaker(runs, "dev", self.cfg))
        runs = self.r("failed", pr=7) + self.r("failed", pr=8)
        self.assertIsNone(hs.compute_breaker(runs, "dev", {"circuit_breaker": {"consecutive_failures": 9, "same_pr_failures": 2}}))

    def test_other_lanes_and_refusals_do_not_count(self):
        runs = [{"lane": "security", "outcome": "failed"}] * 5 + self.r("refused", "refused", "refused")
        self.assertIsNone(hs.compute_breaker(runs, "dev", self.cfg))


class StoreTests(Base):
    def test_record_creates_orphan_branch_and_appends(self):
        h = self.hist()
        self.assertEqual(h.runs(), [])
        self.rec(h, outcome="merged", pr=3, cost_usd=1.5, note="done")
        self.rec(h, outcome="quiet")
        runs = self.hist().runs()
        self.assertEqual([r["outcome"] for r in runs], ["merged", "quiet"])
        self.assertEqual(runs[0]["recorded_at"], "2026-10-02T10:00:00Z")
        files = subprocess.run(["git", "-C", str(self.remote), "ls-tree", "--name-only", hs.DATA_BRANCH],
                               capture_output=True, text=True).stdout.split()
        self.assertEqual(files, [hs.RUNS_FILE])
        parents = subprocess.run(["git", "-C", str(self.remote), "rev-list", "--max-parents=0", hs.DATA_BRANCH],
                                 capture_output=True, text=True).stdout.split()
        self.assertEqual(len(parents), 1)

    def test_secrets_are_scrubbed_before_writing(self):
        h = self.hist()
        self.rec(h, note="leaked ghp_" + "b" * 30)
        raw = (self.remote / "x").exists() or subprocess.run(
            ["git", "-C", str(self.remote), "show", f"{hs.DATA_BRANCH}:{hs.RUNS_FILE}"], capture_output=True, text=True).stdout
        self.assertNotIn("ghp_", raw)

    def test_invalid_outcome_and_lane_rejected(self):
        h = self.hist()
        with self.assertRaises(hs.HistoryError):
            h.record("dev", "r", "great")
        with self.assertRaises(hs.HistoryError):
            h.record("nope", "r", "failed")

    def test_concurrent_writers_lose_no_records(self):
        self.rec(self.hist(), outcome="quiet")
        errs = []

        def w(i):
            try:
                self.rec(self.hist(), outcome="quiet", run_id=f"c{i}")
            except Exception as e:  # pragma: no cover
                errs.append(e)
        ts = [threading.Thread(target=w, args=(i,)) for i in range(5)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(errs, [])
        self.assertEqual(len(self.hist().runs()), 6)


class PauseTests(Base):
    def test_pause_and_owner_only_unpause(self):
        h = self.hist()
        h.pause("dev", "manual", by="alice")
        self.assertIn("dev", self.hist().pauses())
        with self.assertRaises(hs.Denied):
            self.hist(FakeForge("laneguard-bot", False)).unpause("dev")
        with self.assertRaises(hs.Denied):
            self.hist(FakeForge(None, False)).unpause("dev")
        self.assertIn("dev", self.hist().pauses())
        res = self.hist(FakeForge("alice", True)).unpause("dev")
        self.assertTrue(res["removed"])
        self.assertEqual(self.hist().pauses(), {})

    def test_global_pause_blocks_every_lane(self):
        h = self.hist()
        h.pause(None, "stop all")
        for lane in ("dev", "security"):
            self.assertFalse(h.evaluate(lane)["may_run"])

    def test_breaker_trips_pause_and_cannot_be_reset_by_new_runs(self):
        h = self.hist()
        for _ in range(3):
            self.rec(h, outcome="failed")
        res = h.evaluate("dev")
        self.assertTrue(res["paused"])
        self.assertIn("circuit breaker", res["pause"]["reason"])
        self.assertTrue(h.evaluate("security")["may_run"])
        self.rec(h, outcome="merged")  # a lane cannot clear the flag by "succeeding"
        self.assertFalse(h.evaluate("dev")["may_run"])

    def test_cost_ceiling_uses_current_month_only(self):
        h = self.hist()
        self.rec(h, outcome="merged", cost_usd=6)
        self.assertTrue(h.evaluate("dev")["may_run"])
        self.rec(h, outcome="merged", cost_usd=5)
        res = h.evaluate("dev")
        self.assertTrue(res["over_ceiling"])
        self.assertFalse(res["may_run"])
        self.clock.t = dt.datetime(2026, 11, 1, 1, tzinfo=dt.timezone.utc)
        self.assertTrue(self.hist().evaluate("dev")["may_run"])


class CliTests(Base):
    def test_pause_check_exit_codes_and_record(self):
        import io
        h = self.hist()
        out = io.StringIO()
        self.assertEqual(hs.main(["pause-check", "--lane", "dev"], history=h, out=out), 0)
        self.assertEqual(hs.main(["record", "--lane", "dev", "--run-id", "x", "--outcome", "quiet"], history=h, out=out), 0)
        h.pause("dev", "m")
        self.assertEqual(hs.main(["pause-check", "--lane", "dev"], history=h, out=out), 3)
        self.assertEqual(hs.main(["unpause", "--lane", "dev"], history=self.hist(FakeForge("bot[bot]", False)), out=out), 1)


if __name__ == "__main__":
    unittest.main()
