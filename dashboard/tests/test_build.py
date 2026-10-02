import json
import re
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from dashboard import build

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
XSS = '<script>alert(1)</script><img src=x onerror=alert(2)>"\'&'


def rec(**kw):
    base = {"run_id": "r1", "lane": "dev", "outcome": "merged", "recorded_at": "2026-10-01T10:00:00Z"}
    base.update(kw)
    return base


def page(runs, pauses=None, cfg=None, skipped=0):
    return build.render(build.build_model(runs, pauses or {}, cfg or {}, NOW, skipped))


def visible_markup(doc: str) -> str:
    """The page without the JSON data block and the template's own script/style."""
    doc = re.sub(r'<script type="application/json".*?</script>', "", doc, flags=re.S)
    return re.sub(r"<(script|style)>.*?</\1>", "", doc, flags=re.S)


class Escaping(unittest.TestCase):
    def test_note_and_run_id_escaped(self):
        doc = page([rec(note=XSS, run_id=XSS, lane="dev")])
        vis = visible_markup(doc)
        self.assertNotIn("<script>alert", vis)
        self.assertNotIn("<img src=x", vis)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", vis)
        self.assertEqual(doc.count("<script"), 2)  # data block + page script only

    def test_json_block_cannot_close_script(self):
        doc = page([rec(note="</script><script>alert(1)</script>")])
        m = re.search(r'<script type="application/json" id="data">(.*?)</script>', doc, flags=re.S)
        self.assertIsNotNone(m)
        self.assertNotIn("<", m.group(1))
        data = json.loads(m.group(1))
        self.assertIn("</script>", data["lanes"][0]["recent"][0]["note"])

    def test_lane_and_pause_reason_escaped(self):
        doc = page([rec(lane=XSS)], pauses={XSS: {"reason": XSS}})
        self.assertNotIn("<img src=x", visible_markup(doc))

    def test_template_tokens_in_data_not_resubstituted(self):
        doc = page([rec(note="{{DATA_JSON}} {{LANES}}")])
        self.assertEqual(doc.count('id="data"'), 1)
        self.assertIn("{{DATA_JSON}}", doc)

    def test_no_external_requests_or_innerhtml(self):
        doc = page([rec()])
        self.assertNotRegex(doc, r"(src|href)\s*=\s*[\"']https?:")
        self.assertNotIn("innerHTML", doc)
        self.assertNotIn("@import", doc)


class Content(unittest.TestCase):
    def test_empty(self):
        doc = page([])
        self.assertIn("<!doctype html>", doc)
        self.assertIn("No lanes or runs found yet", doc)

    def test_bad_lines_tolerated(self):
        runs, skipped = build.parse_runs('{"lane":"dev","outcome":"merged"}\nnot json\n[1,2]\n\n"x"\n{"lane":')
        self.assertEqual(len(runs), 1)
        self.assertEqual(skipped, 4)
        self.assertIn("4 unreadable line(s)", page(runs, skipped=skipped))

    def test_odd_field_types_do_not_crash(self):
        runs = [rec(cost_usd="abc"), rec(cost_usd=float("nan")), rec(cost_usd=None, lane=None, pr=[1]),
                {"outcome": "corrupt-line"}, rec(recorded_at=None)]
        self.assertIn("Laneguard dashboard", page(runs))

    def test_cost_sum_matches_current_month_only(self):
        runs = [rec(cost_usd=1.25), rec(cost_usd=2.5, lane="security"),
                rec(cost_usd=100, recorded_at="2026-09-30T23:00:00Z"), rec(cost_usd="bad")]
        m = build.build_model(runs, {}, {"budgets": {"monthly_cost_ceiling_usd": 10}}, NOW)
        self.assertAlmostEqual(m["month_cost_usd"], 3.75)
        self.assertAlmostEqual(sum(l["month_cost_usd"] for l in m["lanes"]), 3.75)
        self.assertFalse(m["over_ceiling"])
        doc = build.render(m)
        self.assertIn("$3.75", doc)
        self.assertIn("$10.00 ceiling", doc)
        m2 = build.build_model(runs, {}, {"budgets": {"monthly_cost_ceiling_usd": 3}}, NOW)
        self.assertTrue(m2["over_ceiling"])

    def test_matches_history_month_cost(self):
        from guard import history
        runs = [rec(cost_usd=1.1), rec(cost_usd=2.2)]
        self.assertAlmostEqual(build.build_model(runs, {}, {}, NOW)["month_cost_usd"],
                               history.month_cost(runs, "2026-10"))

    def test_pause_and_breaker(self):
        runs = [rec(outcome="failed", recorded_at=f"2026-10-01T0{i}:00:00Z") for i in range(3)]
        m = build.build_model(runs, {"dev": {"reason": "why"}}, {}, NOW)
        lane = m["lanes"][0]
        self.assertTrue(lane["paused"])
        self.assertEqual(lane["breaker"]["streak"], 3)
        self.assertTrue(lane["breaker"]["tripped"])
        self.assertIn("PAUSED", build.render(m))

    def test_global_pause_applies_to_all_lanes(self):
        m = build.build_model([rec(), rec(lane="security")], {"*": {"reason": "x"}}, {}, NOW)
        self.assertTrue(all(l["paused"] for l in m["lanes"]))
        self.assertTrue(m["global_pause"])

    def test_config_lanes_listed_without_runs(self):
        cfg = {"lanes": {"dev": {}, "design": {}}}
        self.assertEqual([l["name"] for l in build.build_model([], {}, cfg, NOW)["lanes"]], ["dev", "design"])

    def test_cli_files_and_paused_dir(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / "runs.jsonl").write_text(json.dumps(rec(note="hi")) + "\n{bad\n")
            (t / "PAUSED.dev").write_text(json.dumps({"reason": "manual"}))
            (t / "PAUSED").write_text("plain text reason")
            out = t / "site" / "index.html"
            rc = build.main(["--runs", str(t / "runs.jsonl"), "--paused-dir", str(t), "--out", str(out)])
            self.assertEqual(rc, 0)
            doc = out.read_text()
            self.assertIn("manual", doc)
            self.assertIn("All lanes are paused", doc)

    def test_cli_missing_runs_file_renders_empty(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "i.html"
            self.assertEqual(build.main(["--runs", str(Path(t) / "none.jsonl"), "--out", str(out)]), 0)
            self.assertIn("No lanes or runs", out.read_text())


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"],
                        "HOME": str(cwd)})


class GitRoundTrip(unittest.TestCase):
    def test_reads_data_branch(self):
        with tempfile.TemporaryDirectory() as t:
            repo = Path(t) / "repo"
            repo.mkdir()
            git(repo, "init", "-q")
            git(repo, "config", "commit.gpgsign", "false")
            (repo / "README").write_text("main")
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "init")
            git(repo, "checkout", "-q", "--orphan", "laneguard-data")
            git(repo, "rm", "-rfq", ".")
            lines = [rec(cost_usd=0.5, note=XSS), rec(run_id="r2", outcome="failed", cost_usd=1.0)]
            (repo / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in lines) + "\ngarbage\n")
            (repo / "PAUSED.dev").write_text(json.dumps({"reason": "breaker"}))
            (repo / "other.txt").write_text("ignored")
            git(repo, "add", "-A")
            git(repo, "commit", "-q", "-m", "data")
            git(repo, "checkout", "-q", "-b", "main2")  # data branch is no longer checked out
            text, pauses = build.read_from_git(repo)
            runs, skipped = build.parse_runs(text)
            self.assertEqual(len(runs), 2)
            self.assertEqual(skipped, 1)
            self.assertEqual(pauses["dev"]["reason"], "breaker")
            out = Path(t) / "out" / "index.html"
            self.assertEqual(build.main(["--from-git", str(repo), "--out", str(out),
                                         "--now", "2026-10-02T00:00:00Z"]), 0)
            doc = out.read_text()
            self.assertIn("$1.50", doc)
            self.assertNotIn("<img src=x", visible_markup(doc))

    def test_missing_branch_is_empty(self):
        with tempfile.TemporaryDirectory() as t:
            repo = Path(t)
            git(repo, "init", "-q")
            self.assertEqual(build.read_from_git(repo), ("", {}))
            self.assertEqual(build.read_from_git(repo / "nonexistent"), ("", {}))


if __name__ == "__main__":
    unittest.main()
