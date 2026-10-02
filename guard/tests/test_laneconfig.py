import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import laneconfig as lc  # noqa: E402

README_CONFIG = """
project: acme-billing
repo: acme/acme-billing
owners: [your-github-login]        # who can approve gates and change protected paths
approvals_required: 1

profile: standard                  # minimal | standard | full
mode: propose                      # observe | propose | autonomous  (per-lane override allowed)

lanes:
  dev:      { label: laneguard,          schedule: "every 2h", owns: [PROJECT_STATE.md], mode: propose }
  security: { label: laneguard-security, schedule: "every 4h", owns: [docs/security/],  mode: propose }

limits:                            # every timing is derived from this block
  run_max_minutes: 30
  lock_ttl_minutes: 45             # run_max + 15
  heartbeat_minutes: 10
  claim_expiry_hours: 24

budgets:
  per_run: { max_turns: 60, max_tokens: 2000000 }
  monthly_cost_ceiling_usd: 200
  max_open_prs_per_lane: 2
  max_issues_created_per_day: 5

circuit_breaker: { consecutive_failures: 3, same_pr_failures: 2 }

validation:                        # your commands; Laneguard is language-agnostic
  lint: "npm run lint"
  test: "npm test"
  build: "npm run build"

models:                            # tiers, not IDs
  observer: fastest
  triager: mid
  implementer: mid
  reviewer-dev: strongest

extra_gates: []                    # additive only
extra_protected_paths: []          # additive only
"""


class YamlSubsetTests(unittest.TestCase):
    def test_readme_config_parses_and_validates(self):
        raw = lc.loads(README_CONFIG)
        self.assertEqual(raw["owners"], ["your-github-login"])
        self.assertEqual(raw["lanes"]["dev"]["owns"], ["PROJECT_STATE.md"])
        self.assertEqual(raw["budgets"]["per_run"]["max_tokens"], 2000000)
        self.assertEqual(raw["validation"]["lint"], "npm run lint")
        self.assertEqual(raw["extra_gates"], [])
        cfg = lc._merge_defaults(raw)
        self.assertEqual(lc.validate(cfg), [])

    def test_block_sequences_and_maps(self):
        doc = """
a:
  - one
  - two
b:
- x: 1
  y: 2
- x: 3
  y: [4, 5]
c: {k: "v: with colon", n: null}
"""
        v = lc.loads(doc)
        self.assertEqual(v["a"], ["one", "two"])
        self.assertEqual(v["b"], [{"x": 1, "y": 2}, {"x": 3, "y": [4, 5]}])
        self.assertEqual(v["c"], {"k": "v: with colon", "n": None})

    def test_scalars(self):
        v = lc.loads("a: true\nb: false\nc: ~\nd: 3.5\ne: 'it''s'\nf: \"tab\\there\"\ng: 12\nh: a#b\n")
        self.assertIs(v["a"], True)
        self.assertIs(v["b"], False)
        self.assertIsNone(v["c"])
        self.assertEqual(v["d"], 3.5)
        self.assertEqual(v["e"], "it's")
        self.assertEqual(v["f"], "tab\there")
        self.assertEqual(v["g"], 12)
        self.assertEqual(v["h"], "a#b")  # '#' not preceded by space is not a comment

    def test_comment_inside_quotes_is_kept(self):
        v = lc.loads('a: "x # y"  # real comment\n')
        self.assertEqual(v["a"], "x # y")

    def test_literal_block_scalar(self):
        doc = "rules: |\n  Never store card data.\n  Money is integer cents.\nnext: 1\n"
        v = lc.loads(doc)
        self.assertEqual(v["rules"], "Never store card data.\nMoney is integer cents.\n")
        self.assertEqual(v["next"], 1)

    def test_duplicate_key_rejected(self):
        with self.assertRaises(lc.YamlError):
            lc.loads("a: 1\na: 2\n")

    def test_anchor_rejected(self):
        with self.assertRaises(lc.YamlError):
            lc.loads("a: &x 1\n")

    def test_bad_indentation_rejected(self):
        with self.assertRaises(lc.YamlError):
            lc.loads("a:\n    b: 1\n  c: 2\n")

    def test_empty_document(self):
        self.assertEqual(lc.loads(""), {})
        self.assertEqual(lc.loads("# only a comment\n"), {})


class ConfigTests(unittest.TestCase):
    def _cfg(self, **over):
        cfg = lc._merge_defaults(lc.loads(README_CONFIG))
        cfg.update(over)
        return cfg

    def test_missing_owner_is_error(self):
        self.assertTrue(any("owners" in e for e in lc.validate(self._cfg(owners=[]))))

    def test_bad_mode_is_error(self):
        self.assertTrue(any("mode" in e for e in lc.validate(self._cfg(mode="yolo"))))

    def test_ttl_must_exceed_run_max(self):
        cfg = self._cfg()
        cfg["limits"]["lock_ttl_minutes"] = 20
        self.assertTrue(any("lock_ttl_minutes" in e for e in lc.validate(cfg)))

    def test_duplicate_lane_labels_rejected(self):
        cfg = self._cfg()
        cfg["lanes"]["security"]["label"] = "laneguard"
        self.assertTrue(any("already used" in e for e in lc.validate(cfg)))

    def test_unknown_model_tier_rejected(self):
        cfg = self._cfg()
        cfg["models"]["implementer"] = "gpt-9"
        self.assertTrue(any("tier" in e for e in lc.validate(cfg)))

    def test_defaults_fill_in(self):
        cfg = lc._merge_defaults({"project": "p", "repo": "o/p", "owners": ["o"], "profile": "minimal",
                                  "lanes": {"dev": {}}})
        self.assertEqual(cfg["limits"]["lock_ttl_minutes"], 45)
        self.assertEqual(cfg["lanes"]["dev"]["label"], "laneguard")
        self.assertEqual(cfg["lanes"]["dev"]["mode"], "propose")
        self.assertEqual(cfg["models"]["reviewer-dev"], "strongest")


class PathTests(unittest.TestCase):
    def test_protected_matching(self):
        cfg = lc._merge_defaults(lc.loads(README_CONFIG))
        for p in (".laneguard/guard/check.py", ".laneguard/guard/tests/x.py", ".laneguard/config.yaml",
                  ".laneguard/plugin.lock", ".github/workflows/laneguard-guard.yml",
                  ".github/CODEOWNERS", ".claude/settings.json", ".claude/agents/x.md"):
            self.assertTrue(lc.is_protected(p, cfg), p)
        for p in ("src/app.py", ".laneguard/state.yaml", ".laneguard/decisions.yaml",
                  ".github/workflows/ci.yml", "PROJECT_STATE.md"):
            self.assertFalse(lc.is_protected(p, cfg), p)

    def test_extra_protected_is_additive(self):
        cfg = lc._merge_defaults(lc.loads(README_CONFIG))
        cfg["extra_protected_paths"] = ["infra/**"]
        self.assertTrue(lc.is_protected("infra/main.tf", cfg))
        self.assertTrue(lc.is_protected(".claude/settings.json", cfg))

    def test_glob_semantics(self):
        self.assertTrue(lc.path_matches("docs/security/", "docs/security/a/b.md"))
        self.assertFalse(lc.path_matches("docs/security/", "docs/other/b.md"))
        self.assertTrue(lc.path_matches("**/*.tf", "a/b/c.tf"))
        self.assertTrue(lc.path_matches("**/*.tf", "c.tf"))
        self.assertFalse(lc.path_matches("*.md", "docs/a.md"))

    def test_full_sha(self):
        self.assertTrue(lc.is_full_sha("a" * 40))
        self.assertFalse(lc.is_full_sha("main"))
        self.assertFalse(lc.is_full_sha("abc123"))
        self.assertFalse(lc.is_full_sha("A" * 40))


if __name__ == "__main__":
    unittest.main()
