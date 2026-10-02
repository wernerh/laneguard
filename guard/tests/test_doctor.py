import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import allowlist  # noqa: E402
import doctor as dr  # noqa: E402
import laneconfig as lc  # noqa: E402

SHA = "a" * 40
CONFIG = """project: demo
repo: acme/demo
owners: [alice]
profile: standard
mode: propose
lanes:
  dev: { label: laneguard, schedule: "every 2h", owns: [PROJECT_STATE.md], mode: propose }
validation:
  test: "npm test"
"""
GUARD_WF = """name: laneguard-guard
on: [pull_request]
permissions:
  contents: read
jobs:
  check:
    name: laneguard-guard / check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@%s
      - run: python3 trusted/check.py
""" % SHA
LANE_WF = """name: laneguard-lane-dev
on:
  schedule:
    - cron: "0 */2 * * *"
permissions:
  contents: write
concurrency: laneguard-dev
jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@%s
      - run: claude -p "/laneguard:run dev"
""" % SHA
CODEOWNERS = """* @alice
/.laneguard/ @alice
/.github/ @alice
/.claude/ @alice
"""

GOOD_RULES = {
    "permissions": {"admin": False, "maintain": False, "push": True},
    "effective_rules": [
        {"type": "pull_request", "parameters": {"require_code_owner_review": True, "required_approving_review_count": 1}},
        {"type": "required_status_checks", "parameters": {"required_status_checks": [
            {"context": dr.GUARD_CHECK_CONTEXT, "integration_id": dr.GITHUB_ACTIONS_APP_ID}]}},
        {"type": "non_fast_forward"}, {"type": "deletion"},
    ],
    "classic_protection": None, "rulesets": [],
}


def build(root: Path, config=CONFIG):
    (root / ".laneguard" / "guard").mkdir(parents=True)
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".laneguard" / "config.yaml").write_text(config)
    (root / ".laneguard" / "plugin.lock").write_text(f"sha: {SHA}\n")
    (root / ".laneguard" / "guard" / "check.py").write_text("print('check')\n")
    h = hashlib.sha256((root / ".laneguard" / "guard" / "check.py").read_bytes()).hexdigest()
    (root / ".laneguard" / "scaffold.version").write_text(
        f"scaffold: 0.1.0\nfiles:\n  .laneguard/guard/check.py: {h}\n")
    (root / ".github" / "CODEOWNERS").write_text(CODEOWNERS)
    (root / ".github" / "workflows" / "laneguard-guard.yml").write_text(GUARD_WF)
    (root / ".github" / "workflows" / "laneguard-lane-dev.yml").write_text(LANE_WF)
    cfg = lc._merge_defaults(lc.loads(config))
    (root / ".claude").mkdir()
    (root / ".claude" / "settings.json").write_text(allowlist.render(allowlist.generate(cfg)))
    (root / ".claude" / "agents").mkdir()
    (root / ".claude" / "agents" / "reviewer-dev.md").write_text("x")


class FakeForge:
    def __init__(self, login="laneguard-bot", rules=None, owner=False):
        self.login, self._rules, self.owner = login, rules if rules is not None else GOOD_RULES, owner

    def whoami(self):
        return self.login

    def is_owner(self, login):
        return self.owner

    def rules(self):
        return self._rules


def run(root, **kw):
    forge = kw.pop("forge", None)
    d = dr.Doctor(str(root), forge=forge, **kw)
    return {c.id: c for c in d.run()}


class Base(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.root = Path(self._t.name)
        build(self.root)

    def tearDown(self):
        self._t.cleanup()


class OfflineTests(Base):
    def test_clean_project_has_no_failures_offline(self):
        res = run(self.root, offline=True)
        self.assertEqual([c.id for c in res.values() if c.status == dr.FAIL], [])

    def test_missing_config_fails_and_stops(self):
        (self.root / ".laneguard" / "config.yaml").unlink()
        res = run(self.root, offline=True)
        self.assertEqual(list(res), ["config"])
        self.assertEqual(res["config"].status, dr.FAIL)

    def test_bot_owner_fails(self):
        c = CONFIG.replace("owners: [alice]", 'owners: [alice, "laneguard-app[bot]"]')
        (self.root / ".laneguard" / "config.yaml").write_text(c)
        self.assertEqual(run(self.root, offline=True)["owners"].status, dr.FAIL)

    def test_short_pin_fails(self):
        (self.root / ".laneguard" / "plugin.lock").write_text("sha: main\n")
        self.assertEqual(run(self.root, offline=True)["engine-pin"].status, dr.FAIL)

    def test_tampered_guard_script_fails(self):
        (self.root / ".laneguard" / "guard" / "check.py").write_text("print('weakened')\n")
        r = run(self.root, offline=True)["scaffold"]
        self.assertEqual(r.status, dr.FAIL)
        self.assertIn("differs", r.detail)

    def test_unrecorded_guard_script_fails(self):
        (self.root / ".laneguard" / "guard" / "extra.py").write_text("x=1\n")
        self.assertIn("not recorded", run(self.root, offline=True)["scaffold"].detail)

    def test_codeowners_missing_and_uncovered(self):
        (self.root / ".github" / "CODEOWNERS").write_text("* @bob\n")
        self.assertEqual(run(self.root, offline=True)["codeowners"].status, dr.FAIL)
        (self.root / ".github" / "CODEOWNERS").unlink()
        self.assertEqual(run(self.root, offline=True)["codeowners"].status, dr.FAIL)

    def test_codeowners_team_only_warns(self):
        (self.root / ".github" / "CODEOWNERS").write_text("* @acme/core\n")
        self.assertEqual(run(self.root, offline=True)["codeowners"].status, dr.WARN)

    def test_loosened_allowlist_fails(self):
        p = self.root / ".claude" / "settings.json"
        s = json.loads(p.read_text())
        s["permissions"]["allow"].append("Bash(curl:*)")
        p.write_text(json.dumps(s))
        self.assertEqual(run(self.root, offline=True)["allowlist"].status, dr.FAIL)

    def test_missing_allowlist_fails(self):
        (self.root / ".claude" / "settings.json").unlink()
        self.assertEqual(run(self.root, offline=True)["allowlist"].status, dr.FAIL)

    def _wf(self, text, name="laneguard-lane-dev.yml"):
        (self.root / ".github" / "workflows" / name).write_text(text)
        return run(self.root, offline=True)["workflows"]

    def test_unpinned_action_fails(self):
        r = self._wf(LANE_WF.replace(SHA, "v4"))
        self.assertEqual(r.status, dr.FAIL)
        self.assertIn("not pinned", r.detail)

    def test_pull_request_target_fails(self):
        self.assertIn("pull_request_target", self._wf(GUARD_WF.replace("[pull_request]", "[pull_request_target]"),
                                                       "laneguard-guard.yml").detail)

    def test_guard_job_name_must_equal_required_check_context(self):
        """Issue #12: the required-check context is the job's literal name."""
        r = self._wf(GUARD_WF.replace("name: laneguard-guard / check", "name: guard"), "laneguard-guard.yml")
        self.assertEqual(r.status, dr.FAIL)
        self.assertIn("no job named", r.detail)

    def test_timeout_must_match_config(self):
        r = self._wf(LANE_WF.replace("timeout-minutes: 30", "timeout-minutes: 90"))
        self.assertIn("timeout-minutes", r.detail)

    def test_missing_lane_workflow_fails(self):
        (self.root / ".github" / "workflows" / "laneguard-lane-dev.yml").unlink()
        self.assertEqual(run(self.root, offline=True)["workflows"].status, dr.FAIL)

    def test_missing_permissions_block_fails(self):
        r = self._wf(LANE_WF.replace("permissions:\n  contents: write\n", ""))
        self.assertIn("minimal permissions", r.detail)

    def test_reviewer_missing_fails_and_engine_root_satisfies(self):
        (self.root / ".claude" / "agents" / "reviewer-dev.md").unlink()
        self.assertEqual(run(self.root, offline=True)["reviewers"].status, dr.SKIP)
        eng = self.root / "engine"
        (eng / "agents").mkdir(parents=True)
        self.assertEqual(run(self.root, offline=True, engine_root=str(eng))["reviewers"].status, dr.FAIL)
        (eng / "agents" / "reviewer-dev.md").write_text("x")
        self.assertEqual(run(self.root, offline=True, engine_root=str(eng))["reviewers"].status, dr.PASS)

    def test_same_model_reviewer_warns(self):
        c = CONFIG + "models:\n  implementer: strongest\n"
        (self.root / ".laneguard" / "config.yaml").write_text(c)
        self.assertEqual(run(self.root, offline=True)["model-separation"].status, dr.WARN)

    def test_pause_flag_warns(self):
        (self.root / ".laneguard" / "PAUSED").write_text("")
        self.assertEqual(run(self.root, offline=True)["pause"].status, dr.WARN)

    def test_strict_offline_turns_skips_into_failures(self):
        res = run(self.root, offline=True, strict=True)
        self.assertEqual(res["token"].status, dr.FAIL)
        self.assertEqual(res["branch-protection"].status, dr.FAIL)


class CodeownersTests(unittest.TestCase):
    def test_last_match_wins_and_dirs(self):
        rules = dr.parse_codeowners("* @a\n/.github/ @b # c\n")
        self.assertEqual(dr.codeowners_for(rules, ".github/CODEOWNERS"), ["@b"])
        self.assertEqual(dr.codeowners_for(rules, "src/x.py"), ["@a"])
        self.assertEqual(dr.codeowners_for([], "x"), [])

    def test_unanchored_name_matches_anywhere(self):
        self.assertTrue(dr.codeowners_match("*.md", "docs/a/b.md"))
        self.assertFalse(dr.codeowners_match("/*.md", "docs/a.md"))


class OnlineTests(Base):
    def test_good_lane_identity_and_rules_pass(self):
        res = run(self.root, forge=FakeForge(), role="lane")
        self.assertEqual([c.id for c in res.values() if c.status == dr.FAIL], [])
        self.assertEqual(res["token"].status, dr.PASS)

    def test_owner_token_used_by_lane_fails(self):
        res = run(self.root, forge=FakeForge(login="alice", owner=True), role="lane")
        self.assertEqual(res["token"].status, dr.FAIL)

    def test_admin_lane_token_fails(self):
        rules = dict(GOOD_RULES, permissions={"admin": True})
        self.assertEqual(run(self.root, forge=FakeForge(rules=rules), role="lane")["token"].status, dr.FAIL)

    def test_unreachable_forge_skips(self):
        class Boom(FakeForge):
            def whoami(self):
                raise RuntimeError("no network")
        res = run(self.root, forge=Boom())
        self.assertEqual(res["token"].status, dr.SKIP)

    def test_rules_each_missing_guarantee_fails(self):
        cfg = lc._merge_defaults(lc.loads(CONFIG))
        cases = {
            "branch.pull-request": {"effective_rules": [], "classic_protection": None, "rulesets": []},
            "branch.codeowner-review": {"effective_rules": [{"type": "pull_request", "parameters": {}}],
                                         "classic_protection": None, "rulesets": []},
        }
        for cid, rules in cases.items():
            got = {c.id: c for c in dr.analyze_rules(rules, cfg)}
            self.assertEqual(got[cid].status, dr.FAIL, cid)
        no_checks = dict(GOOD_RULES, effective_rules=[r for r in GOOD_RULES["effective_rules"]
                                                       if r["type"] != "required_status_checks"])
        self.assertEqual({c.id: c for c in dr.analyze_rules(no_checks, cfg)}["branch.required-checks"].status, dr.FAIL)
        no_ff = dict(GOOD_RULES, effective_rules=[r for r in GOOD_RULES["effective_rules"] if r["type"] != "non_fast_forward"])
        self.assertEqual({c.id: c for c in dr.analyze_rules(no_ff, cfg)}["branch.force-push"].status, dr.FAIL)

    def test_classic_protection_is_understood(self):
        cfg = lc._merge_defaults(lc.loads(CONFIG))
        classic = {"required_pull_request_reviews": {"require_code_owner_reviews": True, "required_approving_review_count": 1},
                   "required_status_checks": {"contexts": [], "checks": [{"context": dr.GUARD_CHECK_CONTEXT, "app_id": dr.GITHUB_ACTIONS_APP_ID}]},
                   "allow_force_pushes": {"enabled": False}, "allow_deletions": {"enabled": False}}
        got = dr.analyze_rules({"effective_rules": None, "classic_protection": classic, "rulesets": None}, cfg)
        self.assertEqual([c.id for c in got if c.status == dr.FAIL], [])

    def test_app_bypass_fails_and_user_bypass_warns(self):
        cfg = lc._merge_defaults(lc.loads(CONFIG))
        for actor, want in (("Integration", dr.FAIL), ("RepositoryRole", dr.WARN)):
            rules = dict(GOOD_RULES, rulesets=[{"enforcement": "active", "bypass_actors": [{"actor_type": actor}]}])
            self.assertEqual({c.id: c for c in dr.analyze_rules(rules, cfg)}["branch.bypass"].status, want)

    def test_required_check_not_pinned_to_actions_fails(self):
        """Issue #3: a bare context can be satisfied by a forged commit status."""
        cfg = lc._merge_defaults(lc.loads(CONFIG))
        unpinned = dict(GOOD_RULES, effective_rules=[
            r if r["type"] != "required_status_checks" else
            {"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": dr.GUARD_CHECK_CONTEXT}]}}
            for r in GOOD_RULES["effective_rules"]])
        got = {c.id: c for c in dr.analyze_rules(unpinned, cfg)}["branch.required-checks"]
        self.assertEqual(got.status, dr.FAIL)
        self.assertIn("not pinned to GitHub Actions", got.detail)
        classic = {"required_pull_request_reviews": {"require_code_owner_reviews": True, "required_approving_review_count": 1},
                   "required_status_checks": {"contexts": [dr.GUARD_CHECK_CONTEXT], "checks": []},
                   "allow_force_pushes": {"enabled": False}, "allow_deletions": {"enabled": False}}
        got = {c.id: c for c in dr.analyze_rules({"effective_rules": None, "classic_protection": classic, "rulesets": None}, cfg)}
        self.assertEqual(got["branch.required-checks"].status, dr.FAIL)
        wrong_app = dict(GOOD_RULES, effective_rules=[
            r if r["type"] != "required_status_checks" else
            {"type": "required_status_checks", "parameters": {"required_status_checks": [
                {"context": dr.GUARD_CHECK_CONTEXT, "integration_id": 99}]}}
            for r in GOOD_RULES["effective_rules"]])
        self.assertEqual({c.id: c for c in dr.analyze_rules(wrong_app, cfg)}["branch.required-checks"].status, dr.FAIL)

    def test_ruleset_without_bypass_data_skips_not_passes(self):
        """Issue #4: the rulesets list endpoint omits bypass_actors; that is not evidence of none."""
        cfg = lc._merge_defaults(lc.loads(CONFIG))
        listed = dict(GOOD_RULES, rulesets=[{"id": 1, "enforcement": "active", "name": "main"}])
        got = {c.id: c for c in dr.analyze_rules(listed, cfg)}["branch.bypass"]
        self.assertEqual(got.status, dr.SKIP)
        self.assertTrue(got.critical)
        empty = dict(GOOD_RULES, rulesets=[{"id": 1, "enforcement": "active", "bypass_actors": []}])
        self.assertEqual({c.id: c for c in dr.analyze_rules(empty, cfg)}["branch.bypass"].status, dr.PASS)
        disabled = dict(GOOD_RULES, rulesets=[{"id": 1, "enforcement": "disabled"}])
        self.assertEqual({c.id: c for c in dr.analyze_rules(disabled, cfg)}["branch.bypass"].status, dr.PASS)

    def test_autonomous_requires_review_check(self):
        cfg = lc._merge_defaults(lc.loads(CONFIG.replace("mode: propose }", "mode: autonomous }")))
        got = {c.id: c for c in dr.analyze_rules(GOOD_RULES, cfg)}
        self.assertEqual(got["branch.review-check"].status, dr.FAIL)

    def test_unreadable_rules_skip(self):
        cfg = lc._merge_defaults(lc.loads(CONFIG))
        got = dr.analyze_rules({"effective_rules": None, "classic_protection": None, "rulesets": None}, cfg)
        self.assertEqual(got[0].status, dr.SKIP)


class CliTests(Base):
    def test_exit_codes(self):
        self.assertEqual(dr.main(["--root", str(self.root), "--offline", "--json"]), 0)
        (self.root / ".claude" / "settings.json").unlink()
        self.assertEqual(dr.main(["--root", str(self.root), "--offline"]), 1)


if __name__ == "__main__":
    unittest.main()
