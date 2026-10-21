import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "guard"))
import init as ini  # noqa: E402
import doctor as dr  # noqa: E402
import laneconfig as lc  # noqa: E402

SHA = "c" * 40


def run_init(target, *extra, profile="standard"):
    args = ["--profile", profile, "--project", "demo", "--repo", "acme/demo", "--owner", "alice",
            "--engine-sha", SHA, "--target", str(target), *extra]
    return ini.main(args)


class InitTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.t = Path(self._t.name)

    def tearDown(self):
        self._t.cleanup()

    def doctor(self):
        d = dr.Doctor(str(self.t), offline=True, engine_root=str(ROOT))
        return {c.id: c for c in d.run()}

    def test_every_profile_scaffolds_clean_and_passes_offline_doctor(self):
        for profile, lanes in (("minimal", 1), ("standard", 2), ("full", 3)):
            with self.subTest(profile=profile):
                self.setUp()
                self.assertEqual(run_init(self.t, profile=profile, *("--ci", "node", "--validation-test", "npm test")), 0)
                res = self.doctor()
                self.assertEqual([c.detail for c in res.values() if c.status == dr.FAIL], [])
                self.assertEqual(len(list((self.t / ".github" / "workflows").glob("laneguard-lane-*.yml"))), lanes)
                self.assertEqual(res["reviewers"].status, dr.PASS)

    def test_no_placeholders_left_anywhere(self):
        run_init(self.t, "--ci", "python", profile="full")
        for p in self.t.rglob("*"):
            if p.is_file():
                self.assertIsNone(ini.PLACEHOLDER.search(p.read_text(encoding="utf-8")), p)

    def test_starts_in_propose_and_pins_sha(self):
        run_init(self.t)
        text = (self.t / ".laneguard/config.yaml").read_text()
        self.assertIn("\nmode: propose\n", text)
        self.assertNotIn("autonomous", text)
        self.assertIn(f"sha: {SHA}", (self.t / ".laneguard/plugin.lock").read_text())
        cfg = lc._merge_defaults(lc.loads(text))
        self.assertEqual({lane["mode"] for lane in cfg["lanes"].values()}, {"propose"})

    def test_lane_lines_carry_no_mode(self):
        run_init(self.t, profile="full")
        for line in (self.t / ".laneguard/config.yaml").read_text().splitlines():
            if line.startswith("  ") and "label:" in line:
                self.assertNotIn("mode:", line, line)

    # Issue #5, second half: laneconfig.DEFAULT_LANES must not carry a mode either, or _merge_defaults
    # still forces propose. Remove "mode": "propose" from DEFAULT_LANES in guard/laneconfig.py and this activates.
    @unittest.skipIf("mode" in lc.DEFAULT_LANES["dev"], "guard/laneconfig.py DEFAULT_LANES still forces a lane mode (issue #5)")
    def test_lanes_inherit_project_mode(self):
        run_init(self.t, profile="full")
        path = self.t / ".laneguard/config.yaml"
        for line in path.read_text().splitlines():
            if line.startswith("  ") and "label:" in line:
                self.assertNotIn("mode:", line, line)
        lowered = path.read_text().replace("\nmode: propose\n", "\nmode: observe\n")
        cfg = lc._merge_defaults(lc.loads(lowered))
        self.assertEqual(lc.validate(cfg), [])
        self.assertEqual(len(cfg["lanes"]), 3)
        self.assertEqual({lane["mode"] for lane in cfg["lanes"].values()}, {"observe"})

    def test_all_actions_are_sha_pinned(self):
        run_init(self.t, "--ci", "node", profile="full")
        import re
        for wf in (self.t / ".github/workflows").glob("*.yml"):
            for _a, ref in re.findall(r"uses:\s*([^\s@]+)@(\S+)", wf.read_text()):
                self.assertRegex(ref, r"^[0-9a-f]{40}$", wf.name)

    def test_existing_files_are_not_overwritten_without_force(self):
        (self.t / "CLAUDE.md").write_text("mine")
        run_init(self.t)
        self.assertEqual((self.t / "CLAUDE.md").read_text(), "mine")
        run_init(self.t, "--force")
        self.assertNotEqual((self.t / "CLAUDE.md").read_text(), "mine")

    def test_rerun_on_initialised_project_is_refused_without_force(self):
        self.assertEqual(run_init(self.t), 0)
        (self.t / ".laneguard/guard/check.py").write_text("# edited\n")
        before = {p: p.read_text() for p in self.t.rglob("*") if p.is_file()}
        self.assertEqual(run_init(self.t, "--run-max-minutes", "20"), 2)
        self.assertEqual(before, {p: p.read_text() for p in self.t.rglob("*") if p.is_file()})
        self.assertEqual(run_init(self.t, "--dry-run"), 2)
        self.assertEqual(run_init(self.t, "--force"), 0)
        self.assertNotIn("# edited", (self.t / ".laneguard/guard/check.py").read_text())
        self.assertEqual([c.detail for c in self.doctor().values() if c.status == dr.FAIL], [])

    def test_rerun_error_points_at_migrate(self):
        run_init(self.t)
        import io, contextlib
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            run_init(self.t)
        self.assertIn("/laneguard:migrate", err.getvalue())
        self.assertIn("--force", err.getvalue())

    def test_short_run_max_derives_a_valid_heartbeat(self):
        self.assertEqual(run_init(self.t, "--run-max-minutes", "3"), 0)
        cfg = lc._merge_defaults(lc.load_file(self.t / ".laneguard/config.yaml"))
        self.assertEqual(lc.validate(cfg), [])
        lim = cfg["limits"]
        self.assertEqual((lim["run_max_minutes"], lim["lock_ttl_minutes"], lim["heartbeat_minutes"]), (3, 18, 9))
        self.assertEqual([c.detail for c in self.doctor().values() if c.status == dr.FAIL], [])

    def test_heartbeat_derivation(self):
        self.assertEqual(ini.heartbeat_for(45), 10)
        self.assertEqual(ini.heartbeat_for(20), 10)
        self.assertEqual(ini.heartbeat_for(16), 8)
        self.assertEqual(ini.heartbeat_for(1), 1)
        run_init(self.t)
        self.assertIn("heartbeat_minutes: 10", (self.t / ".laneguard/config.yaml").read_text())

    def test_bad_inputs_are_refused(self):
        self.assertEqual(ini.main(["--project", "d", "--repo", "acme/demo", "--owner", "a", "--engine-sha", "main", "--target", str(self.t)]), 2)
        self.assertEqual(ini.main(["--project", "d", "--repo", "acme/demo", "--owner", "app[bot]", "--engine-sha", SHA, "--target", str(self.t)]), 2)
        self.assertEqual(ini.main(["--project", "d", "--repo", "nope", "--owner", "a", "--engine-sha", SHA, "--target", str(self.t)]), 2)
        self.assertEqual(ini.main(["--project", "d", "--repo", "a/b", "--engine-sha", SHA, "--target", str(self.t)]), 2)
        self.assertEqual(ini.main(["--project", "d", "--repo", "a/b", "--owner", "a", "--approvals", "2", "--engine-sha", SHA, "--target", str(self.t)]), 2)

    def test_engine_repo_is_validated_like_repo(self):
        """Issue #15: --engine-repo lands unquoted in workflow YAML."""
        for bad in ("nope", "a/b/c", "acme/demo\n  evil: yes", "a b/c", ""):
            with self.subTest(bad=bad):
                self.setUp()
                self.assertEqual(run_init(self.t, "--engine-repo", bad), 2)
                self.assertFalse((self.t / ".laneguard").exists())
        self.assertEqual(run_init(self.t, "--engine-repo", "fork-org/lane.guard_x"), 0)
        self.assertIn("repository: fork-org/lane.guard_x", (self.t / ".github/workflows/laneguard-lane-dev.yml").read_text())
        self.assertIn("repo: fork-org/lane.guard_x", (self.t / ".laneguard/plugin.lock").read_text())

    def test_project_name_is_quoted_in_config(self):
        """Issue #15: --project is free text and must not be able to inject YAML."""
        name = 'Demo: "the" app\\ #1'
        self.assertEqual(ini.main(["--project", name, "--repo", "acme/demo", "--owner", "alice", "--engine-sha", SHA,
                                   "--target", str(self.t)]), 0)
        text = (self.t / ".laneguard/config.yaml").read_text()
        self.assertIn('project: "Demo: \\"the\\" app\\\\ #1"\n', text)
        cfg = lc._merge_defaults(lc.loads(text))
        self.assertEqual(cfg["project"], name)
        self.assertEqual(lc.validate(cfg), [])
        self.assertIn(f"# {name}: project rules", (self.t / "CLAUDE.md").read_text())  # markdown keeps the bare form
        self.assertEqual([c.detail for c in self.doctor().values() if c.status == dr.FAIL], [])
        # eject/migrate rebuild init's inputs from the parsed config: the name must round-trip unchanged
        a = ini.args_from_project(self.t, SHA)
        self.assertEqual(a.project, name)
        rebuilt = dict(ini.plan_to_map(ini.build_plan(a, ROOT)))[".laneguard/config.yaml"]
        self.assertEqual(rebuilt, text)

    def test_max_turns_lands_in_config_and_workflows(self):
        """Issue #15: one value for budgets.per_run.max_turns and the workflows' --max-turns."""
        self.assertEqual(run_init(self.t, profile="full"), 0)
        cfg = lc._merge_defaults(lc.load_file(self.t / ".laneguard/config.yaml"))
        self.assertEqual(cfg["budgets"]["per_run"]["max_turns"], lc.DEFAULT_BUDGETS["per_run"]["max_turns"])
        for wf in (self.t / ".github/workflows").glob("laneguard-lane-*.yml"):
            self.assertIn("--max-turns 60", wf.read_text(), wf.name)
        self.assertEqual(run_init(self.t, "--max-turns", "25", "--force", profile="full"), 0)
        cfg = lc._merge_defaults(lc.load_file(self.t / ".laneguard/config.yaml"))
        self.assertEqual(cfg["budgets"]["per_run"]["max_turns"], 25)
        for wf in (self.t / ".github/workflows").glob("laneguard-lane-*.yml"):
            self.assertIn("--max-turns 25", wf.read_text(), wf.name)
            self.assertNotIn("--max-turns 60", wf.read_text(), wf.name)
        self.assertEqual([c.detail for c in self.doctor().values() if c.status == dr.FAIL], [])
        self.assertEqual(ini.args_from_project(self.t, SHA).max_turns, 25)
        self.assertEqual(run_init(self.t, "--max-turns", "0", "--force"), 2)
        # editing the config without the workflow (or the reverse) is caught by doctor
        path = self.t / ".laneguard/config.yaml"
        path.write_text(path.read_text().replace("max_turns: 25", "max_turns: 40"))
        self.assertIn("--max-turns is 25, config budgets.per_run.max_turns is 40", self.doctor()["workflows"].detail)

    def test_ci_templates_do_not_persist_credentials_and_install_conditionally(self):
        """Issue #15: CI checkouts keep no token, and installs tolerate a repo without a manifest."""
        for ci, needle in (("python", "if [ -f requirements.txt ]; then python -m pip install -r requirements.txt; fi"),
                           ("node", "if [ -f package-lock.json ] || [ -f npm-shrinkwrap.json ]; then npm ci; else npm install; fi"),
                           ("generic", None)):
            with self.subTest(ci=ci):
                self.setUp()
                self.assertEqual(run_init(self.t, "--ci", ci), 0)
                text = (self.t / ".github/workflows/ci.yml").read_text()
                self.assertIn("persist-credentials: false", text)
                self.assertNotIn("|| true", text)
                if needle:
                    self.assertIn(needle, text)

    def test_guard_workflow_falls_back_to_head_checker_on_bootstrap(self):
        """Issue #15: the bootstrap PR has no .laneguard/guard on the base; the step must not fail."""
        run_init(self.t)
        text = (self.t / ".github/workflows/laneguard-guard.yml").read_text()
        self.assertIn('git cat-file -e "$BASE_SHA:.laneguard/guard/check.py"', text)
        self.assertIn("bootstrap", text)
        self.assertIn("persist-credentials: false", text)
        self.assertIn("GH_TOKEN: ${{ github.token }}", text)
        # exercise the step's shell in a real repo: base has no guard, head adds one
        import subprocess
        step = text.split("run: |", 1)[1].split("- name: Run check.py")[0]
        script = "\n".join(line[10:] if line.startswith(" " * 10) else line for line in step.splitlines())
        repo = self.t / "repo"
        repo.mkdir()
        g = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)
        g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
        (repo / "README").write_text("x\n")
        g("add", "."); g("commit", "-qm", "base")
        base = g("rev-parse", "HEAD").stdout.strip()
        (repo / ".laneguard/guard").mkdir(parents=True)
        (repo / ".laneguard/guard/check.py").write_text("print('head checker')\n")
        g("add", "."); g("commit", "-qm", "bootstrap")
        tmp = self.t / "runner"
        tmp.mkdir()
        p = subprocess.run(["bash", "-e", "-c", script], cwd=str(repo), capture_output=True, text=True,
                           env={"PATH": "/usr/bin:/bin", "BASE_SHA": base, "RUNNER_TEMP": str(tmp)})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("::notice::", p.stdout)
        self.assertEqual((tmp / "trusted/.laneguard/guard/check.py").read_text(), "print('head checker')\n")
        # and with a guard on the base, the base copy wins silently
        (repo / ".laneguard/guard/check.py").write_text("print('weakened')\n")
        g("add", "."); g("commit", "-qm", "weaken")
        base = g("rev-parse", "HEAD~1").stdout.strip()
        tmp2 = self.t / "runner2"
        tmp2.mkdir()
        p = subprocess.run(["bash", "-e", "-c", script], cwd=str(repo), capture_output=True, text=True,
                           env={"PATH": "/usr/bin:/bin", "BASE_SHA": base, "RUNNER_TEMP": str(tmp2)})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("::notice::", p.stdout)
        self.assertEqual((tmp2 / "trusted/.laneguard/guard/check.py").read_text(), "print('head checker')\n")

    def test_tampering_after_init_is_caught(self):
        run_init(self.t)
        (self.t / ".laneguard/guard/check.py").write_text("# weakened\n")
        self.assertEqual(self.doctor()["scaffold"].status, dr.FAIL)

    def test_cron_translation(self):
        self.assertRegex(ini.cron_for("every 2h", 0), r"^\d+ \*/2 \* \* \*$")
        self.assertRegex(ini.cron_for("every 15m", 1), r"^\d+-59/15 \* \* \* \*$")
        self.assertRegex(ini.cron_for("daily", 0), r"^\d+ 6 \* \* \*$")
        with self.assertRaises(ini.InitError):
            ini.cron_for("whenever", 0)
        with self.assertRaises(ini.InitError):
            ini.cron_for("every 2m", 0)

    def test_workflows_are_valid_yaml_when_pyyaml_present(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        run_init(self.t, "--ci", "generic", profile="full")
        for wf in (self.t / ".github/workflows").glob("*.yml"):
            doc = yaml.safe_load(wf.read_text())
            self.assertIn("jobs", doc, wf.name)

    def test_init_sh_wrapper_runs(self):
        p = subprocess.run(["bash", str(ROOT / "scripts/init.sh"), "--project", "d", "--repo", "a/b", "--owner", "a",
                            "--engine-sha", SHA, "--target", str(self.t), "--dry-run"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(".laneguard/config.yaml", json.loads(p.stdout)["would_write"])


if __name__ == "__main__":
    unittest.main()
