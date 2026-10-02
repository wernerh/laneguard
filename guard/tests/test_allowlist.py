import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import allowlist as al  # noqa: E402
import laneconfig as lc  # noqa: E402

CONFIG = """project: demo
repo: acme/demo
owners: [alice]
profile: standard
mode: propose
lanes:
  dev:      { label: laneguard,          schedule: "every 2h", owns: [PROJECT_STATE.md], mode: propose }
  security: { label: laneguard-security, schedule: "every 4h", owns: [docs/security/],  mode: propose }
validation:
  lint: "npm run lint"
  test: "npm test"
  build: ""
extra_protected_paths: [infra/**]
"""


def cfg():
    return lc._merge_defaults(lc.loads(CONFIG))


class GenerateTests(unittest.TestCase):
    def test_every_protected_path_is_denied_for_edit_and_write(self):
        s = al.generate(cfg())["permissions"]
        for pattern in lc.protected_paths(cfg()):
            self.assertIn(f"Edit(/{pattern})", s["deny"], pattern)
            self.assertIn(f"Write(/{pattern})", s["deny"], pattern)
        self.assertIn("Edit(/infra/**)", s["deny"])

    def test_validation_commands_are_allowed_exactly_and_blank_ones_skipped(self):
        allow = al.generate(cfg())["permissions"]["allow"]
        self.assertIn("Bash(npm run lint)", allow)
        self.assertIn("Bash(npm test)", allow)
        self.assertFalse(any(a == "Bash()" for a in allow))

    def test_push_only_to_lane_branches(self):
        allow = al.generate(cfg())["permissions"]["allow"]
        self.assertIn("Bash(git push origin laneguard/*)", allow)
        self.assertIn("Bash(git push origin laneguard-security/*)", allow)
        self.assertFalse(any(a.startswith("Bash(git push origin main") for a in allow))
        self.assertNotIn("Bash(git push:*)", allow)

    def test_force_push_network_cloud_and_secrets_denied(self):
        deny = al.generate(cfg())["permissions"]["deny"]
        for needle in ("git push --force", "git push -f", "git push --force-with-lease", "git rebase",
                       "git filter-branch", "gh", "curl", "wget", "npm install", "pip install", "terraform",
                       "aws", "kubectl", "printenv", "env", "sudo"):
            self.assertIn(f"Bash({needle}:*)", deny, needle)
        for tool in ("WebFetch", "WebSearch", "Read(/.env)", "Read(~/.ssh/**)", "Read(~/.aws/**)"):
            self.assertIn(tool, deny)

    def test_github_goes_through_the_adapter_only(self):
        s = al.generate(cfg())["permissions"]
        self.assertIn("Bash(python3 .laneguard/guard/forge.py:*)", s["allow"])
        self.assertIn("Bash(gh:*)", s["deny"])

    def test_no_allow_rule_is_also_denied(self):
        s = al.generate(cfg())["permissions"]
        self.assertEqual(set(s["allow"]) & set(s["deny"]), set())

    def test_generation_is_deterministic_and_deduplicated(self):
        a = al.render(al.generate(cfg()))
        b = al.render(al.generate(cfg()))
        self.assertEqual(a, b)
        perms = json.loads(a)["permissions"]
        self.assertEqual(len(perms["allow"]), len(set(perms["allow"])))
        self.assertEqual(len(perms["deny"]), len(set(perms["deny"])))


class VerifyTests(unittest.TestCase):
    def good(self):
        return al.render(al.generate(cfg()))

    def test_generated_settings_verify_clean(self):
        self.assertEqual(al.verify(cfg(), self.good()), [])

    def test_extra_allow_is_reported(self):
        s = json.loads(self.good())
        s["permissions"]["allow"].append("Bash(curl:*)")
        self.assertTrue(any("allows more" in p for p in al.verify(cfg(), json.dumps(s))))

    def test_removed_deny_is_reported(self):
        s = json.loads(self.good())
        s["permissions"]["deny"].remove("Edit(/.laneguard/guard/**)")
        self.assertTrue(any("protection removed" in p for p in al.verify(cfg(), json.dumps(s))))

    def test_bypass_permissions_mode_is_reported(self):
        s = json.loads(self.good())
        s["permissions"]["defaultMode"] = "bypassPermissions"
        self.assertTrue(any("defaultMode" in p for p in al.verify(cfg(), json.dumps(s))))

    def test_hooks_and_env_keys_are_reported(self):
        s = json.loads(self.good())
        s["hooks"] = {"Stop": []}
        self.assertTrue(any("hooks" in p for p in al.verify(cfg(), json.dumps(s))))

    def test_invalid_json_is_reported(self):
        self.assertTrue(al.verify(cfg(), "{nope"))

    def test_changing_config_changes_the_expectation(self):
        c = cfg()
        c["extra_protected_paths"] = []
        # settings generated with infra/** no longer verifies against a config without it
        self.assertTrue(any("unexpected" in p or "missing" in p for p in al.verify(c, self.good())))


class CliTests(unittest.TestCase):
    def test_write_then_verify(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".laneguard").mkdir()
            (Path(d) / ".laneguard" / "config.yaml").write_text(CONFIG)
            self.assertEqual(al.main(["verify", "--root", d]), 1)  # missing file
            self.assertEqual(al.main(["generate", "--root", d, "--write"]), 0)
            self.assertEqual(al.main(["verify", "--root", d]), 0)
            p = Path(d) / ".claude" / "settings.json"
            p.write_text(p.read_text().replace('"Edit(/.claude/**)",', ""))
            self.assertEqual(al.main(["verify", "--root", d]), 1)


if __name__ == "__main__":
    unittest.main()
