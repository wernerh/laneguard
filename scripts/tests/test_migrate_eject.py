import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "guard"))
import doctor as dr  # noqa: E402
import eject as ej  # noqa: E402
import init as ini  # noqa: E402
import migrate as mg  # noqa: E402

OLD, NEW = "d" * 40, "e" * 40


def make_engine(dst: Path, tweak=True):
    """A copy of the engine whose guard/allowlist.py differs, standing in for a newer release."""
    for d in ("guard", "templates", "skills", "agents", "commands", ".claude-plugin"):
        shutil.copytree(ROOT / d, dst / d, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    if tweak:
        p = dst / "guard" / "history.py"
        p.write_text(p.read_text() + "\n# newer release\n")
    return dst


class Base(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.root = Path(self._t.name)
        self.proj = self.root / "proj"
        self.proj.mkdir()
        self.engine = make_engine(self.root / "engine")
        ini.main(["--profile", "standard", "--project", "demo", "--repo", "a/b", "--owner", "alice", "--engine-sha", OLD,
                  "--target", str(self.proj), "--plugin-root", str(ROOT)])

    def tearDown(self):
        self._t.cleanup()

    def doctor(self):
        return {c.id: c for c in dr.Doctor(str(self.proj), offline=True, engine_root=str(ROOT)).run()}


class MigrateTests(Base):
    def test_unmodified_project_updates_cleanly_and_passes_doctor(self):
        plan = mg.plan_migration(self.proj, self.engine, NEW)
        self.assertIn(".laneguard/guard/history.py", plan["updates"])
        self.assertEqual(plan["conflicts"], [])
        mg.apply(plan, self.proj)
        self.assertIn("newer release", (self.proj / ".laneguard/guard/history.py").read_text())
        self.assertIn(f"sha: {NEW}", (self.proj / ".laneguard/plugin.lock").read_text())
        self.assertEqual([c.detail for c in self.doctor().values() if c.status == dr.FAIL], [])

    def test_owner_files_are_never_touched(self):
        (self.proj / "CLAUDE.md").write_text("my rules")
        (self.proj / ".laneguard/config.yaml").write_text((self.proj / ".laneguard/config.yaml").read_text() + "# mine\n")
        plan = mg.plan_migration(self.proj, self.engine, NEW)
        mg.apply(plan, self.proj)
        self.assertEqual((self.proj / "CLAUDE.md").read_text(), "my rules")
        self.assertIn("# mine", (self.proj / ".laneguard/config.yaml").read_text())

    def test_locally_edited_guard_script_is_a_conflict_and_doctor_still_fails(self):
        (self.proj / ".laneguard/guard/history.py").write_text("# hacked\n")
        plan = mg.plan_migration(self.proj, self.engine, NEW)
        self.assertEqual(plan["conflicts"], [".laneguard/guard/history.py"])
        with self.assertRaises(ini.InitError):
            mg.apply(plan, self.proj)
        self.assertEqual((self.proj / ".laneguard/guard/history.py").read_text(), "# hacked\n")
        self.assertEqual(self.doctor()["scaffold"].status, dr.FAIL)
        plan = mg.plan_migration(self.proj, self.engine, NEW, overwrite_conflicts=True)
        mg.apply(plan, self.proj)
        self.assertEqual(self.doctor()["scaffold"].status, dr.PASS)

    def test_guard_conflict_refuses_apply_and_writes_nothing(self):
        (self.proj / ".laneguard/guard/history.py").write_text("# hacked\n")
        before = {p: p.read_text() for p in self.proj.rglob("*") if p.is_file()}
        rc = mg.main(["--engine-sha", NEW, "--target", str(self.proj), "--plugin-root", str(self.engine), "--apply", "--json"])
        self.assertEqual(rc, 1)
        after = {p: p.read_text() for p in self.proj.rglob("*") if p.is_file()}
        self.assertEqual(before, after)  # mixed-version guard dir never happens
        self.assertIn(f"sha: {OLD}", (self.proj / ".laneguard/plugin.lock").read_text())
        rc = mg.main(["--engine-sha", NEW, "--target", str(self.proj), "--plugin-root", str(self.engine),
                      "--apply", "--overwrite-conflicts"])
        self.assertEqual(rc, 0)
        self.assertIn("newer release", (self.proj / ".laneguard/guard/history.py").read_text())
        self.assertIn(f"sha: {NEW}", (self.proj / ".laneguard/plugin.lock").read_text())

    def test_non_guard_conflict_is_still_skipped_on_apply(self):
        wf = self.proj / ".github/workflows/laneguard-lane-dev.yml"
        wf.write_text(wf.read_text() + "# tuned locally\n")
        rc = mg.main(["--engine-sha", NEW, "--target", str(self.proj), "--plugin-root", str(self.engine), "--apply"])
        self.assertEqual(rc, 1)
        self.assertIn("# tuned locally", wf.read_text())
        self.assertIn("newer release", (self.proj / ".laneguard/guard/history.py").read_text())
        self.assertIn(f"sha: {NEW}", (self.proj / ".laneguard/plugin.lock").read_text())

    def test_changelog_and_exit_codes(self):
        self.assertEqual(mg.main(["--engine-sha", NEW, "--target", str(self.proj), "--plugin-root", str(self.engine)]), 0)
        (self.proj / ".laneguard/guard/lock.py").write_text("x")
        self.assertEqual(mg.main(["--engine-sha", NEW, "--target", str(self.proj), "--plugin-root", str(self.engine)]), 1)
        self.assertEqual(mg.main(["--engine-sha", "main", "--target", str(self.proj), "--plugin-root", str(self.engine)]), 2)

    def test_not_initialised_is_an_error(self):
        self.assertEqual(mg.main(["--engine-sha", NEW, "--target", str(self.root), "--plugin-root", str(self.engine)]), 2)


class EjectTests(Base):
    def test_eject_vendors_engine_and_passes_doctor_without_engine_root(self):
        self.assertEqual(ej.main(["--engine-sha", OLD, "--target", str(self.proj), "--apply"]), 0)
        self.assertTrue((self.proj / ".claude/agents/reviewer-dev.md").is_file())
        self.assertTrue((self.proj / ".claude/skills/core/SKILL.md").is_file())
        self.assertTrue((self.proj / ".claude/commands/laneguard-run.md").is_file())
        self.assertNotIn("/laneguard:", (self.proj / ".claude/commands/laneguard-run.md").read_text())
        lock = (self.proj / ".laneguard/plugin.lock").read_text()
        self.assertIn("vendored: true", lock)
        wf = (self.proj / ".github/workflows/laneguard-lane-dev.yml").read_text()
        self.assertNotIn("laneguard-engine", wf)
        self.assertIn("/laneguard-run dev", wf)
        d = dr.Doctor(str(self.proj), offline=True)  # no engine root: must rely on vendored agents
        res = {c.id: c for c in d.run()}
        self.assertEqual([c.detail for c in res.values() if c.status == dr.FAIL], [])
        self.assertEqual(res["reviewers"].status, dr.PASS)

    def test_settings_json_is_not_replaced_by_eject(self):
        before = (self.proj / ".claude/settings.json").read_text()
        ej.main(["--engine-sha", OLD, "--target", str(self.proj), "--apply"])
        self.assertEqual((self.proj / ".claude/settings.json").read_text(), before)

    def test_dry_run_writes_nothing_and_bad_sha_refused(self):
        ej.main(["--engine-sha", OLD, "--target", str(self.proj)])
        self.assertFalse((self.proj / ".claude/agents").exists())
        self.assertEqual(ej.main(["--engine-sha", "v1", "--target", str(self.proj)]), 2)

    def test_migrate_after_eject_is_refused_and_writes_nothing(self):
        ej.main(["--engine-sha", OLD, "--target", str(self.proj), "--apply"])
        before = {p: p.read_text() for p in self.proj.rglob("*") if p.is_file()}
        with self.assertRaises(ini.InitError) as cm:
            mg.plan_migration(self.proj, self.engine, NEW)
        self.assertIn("eject", str(cm.exception))
        rc = mg.main(["--engine-sha", NEW, "--target", str(self.proj), "--plugin-root", str(self.engine), "--apply"])
        self.assertEqual(rc, 2)
        after = {p: p.read_text() for p in self.proj.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertIn("vendored: true", (self.proj / ".laneguard/plugin.lock").read_text())
        self.assertNotIn("laneguard-engine", (self.proj / ".github/workflows/laneguard-lane-dev.yml").read_text())


if __name__ == "__main__":
    unittest.main()
