import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check as ck  # noqa: E402
import laneconfig as lc  # noqa: E402

SHA = "a" * 40
CONFIG = """project: demo
repo: acme/demo
owners: [alice]
approvals_required: 1
profile: standard
mode: propose
lanes:
  dev:      { label: laneguard,          schedule: "every 2h", owns: [PROJECT_STATE.md], mode: propose }
  security: { label: laneguard-security, schedule: "every 4h", owns: [docs/security/],  mode: propose }
"""
BASE_FILES = {
    ".laneguard/config.yaml": CONFIG,
    ".laneguard/plugin.lock": f"repo: wernerh/laneguard\nsha: {SHA}\nversion: 0.1.0\n",
    ".laneguard/guard/check.py": "print('guard')\n",
    ".laneguard/PAUSED.dev": "paused for testing\n",
    ".github/CODEOWNERS": "* @alice\n",
    ".github/workflows/laneguard-guard.yml": "name: guard\n",
    ".github/workflows/ci.yml": "jobs:\n  t:\n    steps:\n      - run: npm test\n      - run: npm run lint\n",
    ".claude/settings.json": "{}\n",
    "src/app.py": "def add(a, b):\n    return a + b\n",
    "tests/test_app.py": "def test_add():\n    assert 1 == 1\n\ndef test_sub():\n    assert 2 == 2\n",
    "PROJECT_STATE.md": "next: nothing\n",
    "docs/security/notes.md": "# notes\n",
    ".coveragerc": "[report]\nfail_under = 90\n",
    "package.json": '{"scripts": {"test": "jest"}}\n',
}


def run(*args, cwd):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Repo:
    def __init__(self, files=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        run("git", "init", "--quiet", "-b", "main", cwd=self.dir)
        run("git", "config", "user.email", "t@t", cwd=self.dir)
        run("git", "config", "user.name", "t", cwd=self.dir)
        self.write(files if files is not None else BASE_FILES)
        run("git", "add", "-A", cwd=self.dir)
        run("git", "commit", "--quiet", "-m", "base", cwd=self.dir)
        self.base = run("git", "rev-parse", "HEAD", cwd=self.dir)

    def write(self, files):
        for p, content in files.items():
            f = Path(self.dir) / p
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(content)

    def delete(self, *paths):
        for p in paths:
            (Path(self.dir) / p).unlink()

    def commit(self):
        run("git", "add", "-A", cwd=self.dir)
        run("git", "commit", "--quiet", "-m", "head", cwd=self.dir)
        return run("git", "rev-parse", "HEAD", cwd=self.dir)

    def check(self, author="bob", author_type="User", labels=(), linked=(), trust=None, lock=None):
        head = self.commit()
        changes = ck.collect_changes(self.dir, self.base, head)
        ctx = ck.build_context(self.dir, self.base, head, author, author_type, labels, linked, offline=True,
                               trust_issue=trust, lock_status=lock)
        return ck.run_checks(changes, ctx)

    def close(self):
        self.tmp.cleanup()


def errors(findings, check=None):
    return [f for f in findings if f.severity == ck.ERROR and (check is None or f.check == check)]


def warnings(findings, check=None):
    return [f for f in findings if f.severity == ck.WARNING and (check is None or f.check == check)]


class CheckTestCase(unittest.TestCase):
    def repo(self, files=None):
        r = Repo(files)
        self.addCleanup(r.close)
        return r


class DiffParsingTests(unittest.TestCase):
    def test_line_numbers_and_statuses(self):
        r = Repo()
        try:
            r.write({"src/app.py": "def add(a, b):\n    return a + b + 1\n", "new.txt": "hello\n"})
            r.delete("PROJECT_STATE.md")
            head = r.commit()
            by = {c.path: c for c in ck.collect_changes(r.dir, r.base, head)}
            self.assertEqual(by["src/app.py"].status, "M")
            self.assertEqual(by["src/app.py"].added, [(2, "    return a + b + 1")])
            self.assertEqual(by["src/app.py"].removed, [(2, "    return a + b")])
            self.assertEqual(by["new.txt"].status, "A")
            self.assertEqual(by["PROJECT_STATE.md"].status, "D")
        finally:
            r.close()


class ProtectedPathTests(CheckTestCase):
    PATHS = [".laneguard/guard/check.py", ".claude/settings.json", ".github/CODEOWNERS",
             ".github/workflows/laneguard-guard.yml", ".laneguard/config.yaml", ".laneguard/plugin.lock"]

    def test_clean_change_by_non_owner_passes(self):
        r = self.repo()
        r.write({"src/app.py": "def add(a, b):\n    return a + b  # ok\n"})
        self.assertEqual(errors(r.check("bob")), [])

    def test_non_owner_edit_of_each_protected_path_fails(self):
        for path in self.PATHS:
            r = self.repo()
            r.write({path: BASE_FILES[path] + "\n# tweak\n"})
            found = errors(r.check("bob"), "protected-paths")
            self.assertTrue(any(f.path == path for f in found), path)

    def test_owner_edit_passes(self):
        r = self.repo()
        r.write({".laneguard/guard/check.py": "print('guard v2')\n", ".github/CODEOWNERS": "* @alice\n/x @alice\n"})
        self.assertEqual(errors(r.check("alice"), "protected-paths"), [])

    def test_bot_with_an_owner_name_is_not_an_owner(self):
        r = self.repo()
        r.write({".claude/settings.json": '{"x": 1}\n'})
        self.assertTrue(errors(r.check("alice", author_type="Bot"), "protected-paths"))
        r2 = self.repo()
        r2.write({".claude/settings.json": '{"x": 1}\n'})
        self.assertTrue(errors(r2.check("alice[bot]"), "protected-paths"))

    def test_config_is_read_from_base_so_a_pr_cannot_make_itself_an_owner(self):
        r = self.repo()
        r.write({".laneguard/config.yaml": CONFIG.replace("owners: [alice]", "owners: [alice, bob]"),
                 ".laneguard/guard/check.py": "print('pwned')\n"})
        found = errors(r.check("bob"), "protected-paths")
        self.assertEqual(len(found), 2)

    def test_adding_a_protected_path_via_config_is_additive_from_base_only(self):
        files = dict(BASE_FILES)
        files[".laneguard/config.yaml"] = CONFIG + "extra_protected_paths: [infra/**]\n"
        r = self.repo(files)
        r.write({"infra/main.tf": "x\n"})
        self.assertTrue(errors(r.check("bob"), "protected-paths"))

    def test_deleting_a_pause_flag_is_protected_creating_one_is_not(self):
        r = self.repo()
        r.delete(".laneguard/PAUSED.dev")
        self.assertTrue(errors(r.check("bob"), "protected-paths"))
        r2 = self.repo()
        r2.write({".laneguard/PAUSED.security": "breaker tripped\n"})
        self.assertEqual(errors(r2.check("bob"), "protected-paths"), [])
        r3 = self.repo()
        r3.delete(".laneguard/PAUSED.dev")
        self.assertEqual(errors(r3.check("alice"), "protected-paths"), [])

    def test_moving_a_protected_file_away_is_caught(self):
        r = self.repo()
        run("git", "mv", ".laneguard/guard/check.py", "src/check_moved.py", cwd=r.dir)
        found = errors(r.check("bob"), "protected-paths")
        self.assertTrue(any(f.path == ".laneguard/guard/check.py" for f in found))

    def test_owner_list_with_a_bot_is_an_error(self):
        files = dict(BASE_FILES)
        files[".laneguard/config.yaml"] = CONFIG.replace("owners: [alice]", "owners: [alice, \"laneguard-app[bot]\"]")
        r = self.repo(files)
        r.write({"src/app.py": "x = 1\n"})
        self.assertTrue(any("bot identity" in f.message for f in errors(r.check("alice"), "protected-paths")))


class WeakenedCheckTests(CheckTestCase):
    def assert_flagged(self, files, deletes=(), contains=None, author="bob"):
        r = self.repo()
        r.write(files)
        r.delete(*deletes)
        found = errors(r.check(author), "weakened-checks")
        self.assertTrue(found, files)
        if contains:
            self.assertTrue(any(contains in f.message for f in found), [f.message for f in found])

    def test_disabled_test_python(self):
        self.assert_flagged({"tests/test_app.py": "import pytest\n@pytest.mark.skip\ndef test_add():\n    assert 1 == 1\n\ndef test_sub():\n    assert 2 == 2\n"},
                            contains="skip")

    def test_conditional_skip_forms_are_flagged(self):
        for dec in ("@unittest.skipIf(True, 'x')", "@unittest.skipUnless(False, 'x')", "@pytest.mark.skipif(True, reason='x')"):
            with self.subTest(dec):
                self.assert_flagged({"tests/test_app.py": f"import pytest, unittest\n{dec}\ndef test_add():\n    assert 1 == 1\n\ndef test_sub():\n    assert 2 == 2\n"},
                                    contains="skip")

    def test_disabled_test_js(self):
        self.assert_flagged({"web/app.test.js": "it.skip('works', () => {})\n"}, contains="skip")
        self.assert_flagged({"web/app2.test.js": "describe.only('x', () => {})\n"}, contains=".only")

    def test_owner_gets_a_warning_not_an_error(self):
        r = self.repo()
        r.write({"tests/test_app.py": "import pytest\n@pytest.mark.skip\ndef test_add():\n    pass\n\ndef test_sub():\n    pass\n"})
        found = r.check("alice")
        self.assertEqual(errors(found, "weakened-checks"), [])
        self.assertTrue(warnings(found, "weakened-checks"))

    def test_deleted_test_file(self):
        self.assert_flagged({}, deletes=["tests/test_app.py"], contains="deleted")

    def test_moved_test_file_is_not_flagged(self):
        r = self.repo()
        run("git", "mv", "tests/test_app.py", "tests/unit/test_app.py", cwd=r.dir) if (Path(r.dir) / "tests/unit").mkdir(parents=True, exist_ok=True) is None else None
        self.assertEqual(errors(r.check("bob"), "weakened-checks"), [])

    def test_net_removal_of_test_cases(self):
        self.assert_flagged({"tests/test_app.py": "def test_add():\n    assert 1 == 1\n"}, contains="removed")

    def test_adding_tests_is_fine(self):
        r = self.repo()
        r.write({"tests/test_app.py": BASE_FILES["tests/test_app.py"] + "\ndef test_mul():\n    assert 3 == 3\n"})
        self.assertEqual(errors(r.check("bob"), "weakened-checks"), [])

    def test_threshold_lowered(self):
        self.assert_flagged({".coveragerc": "[report]\nfail_under = 70\n"}, contains="lowered")

    def test_threshold_raised_is_fine_and_removed_is_flagged(self):
        r = self.repo()
        r.write({".coveragerc": "[report]\nfail_under = 95\n"})
        self.assertEqual(errors(r.check("bob"), "weakened-checks"), [])
        self.assert_flagged({".coveragerc": "[report]\n"}, contains="removed")

    def test_max_warnings_raised(self):
        files = dict(BASE_FILES)
        files["package.json"] = '{"scripts": {"lint": "eslint . --max-warnings 0"}}\n'
        r = self.repo(files)
        r.write({"package.json": '{"scripts": {"lint": "eslint . --max-warnings 500"}}\n'})
        self.assertTrue(any("raised" in f.message for f in errors(r.check("bob"), "weakened-checks")))

    def test_bypass_flags(self):
        self.assert_flagged({"scripts/push.sh": "git push --no-verify\n"}, contains="no-verify")

    def test_ci_made_non_blocking(self):
        self.assert_flagged({".github/workflows/ci.yml": "jobs:\n  t:\n    steps:\n      - run: npm test || true\n      - run: npm run lint\n"})
        self.assert_flagged({".github/workflows/ci2.yml": "jobs:\n  t:\n    steps:\n      - run: x\n        continue-on-error: true\n"},
                            contains="continue-on-error")

    def test_ci_step_removed(self):
        self.assert_flagged({".github/workflows/ci.yml": "jobs:\n  t:\n    steps:\n      - run: npm test\n"},
                            contains="removed from CI")

    def test_blanket_lint_suppression(self):
        self.assert_flagged({"src/x.js": "/* eslint-disable */\nconst a = 1\n"}, contains="suppression")
        self.assert_flagged({"src/y.py": "# flake8: noqa\nx = 1\n"}, contains="suppression")

    def test_branch_protection_config_edit(self):
        self.assert_flagged({".github/settings.yml": "branches:\n  - name: main\n    protection: null\n"},
                            contains="branch-protection")

    def test_docs_mentioning_skips_are_ignored(self):
        r = self.repo()
        r.write({"docs/testing.md": "Never use @pytest.mark.skip or --no-verify.\n"})
        self.assertEqual(errors(r.check("bob"), "weakened-checks"), [])


class SecretTests(CheckTestCase):
    # secrets are assembled at runtime so this file itself never contains a matchable literal
    FAKES = {
        "AWS access key id": "AK" + "IA" + "ABCDEFGHIJKLMNOP",
        "GitHub token": "gh" + "p_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8",
        "Slack token": "xo" + "xb-" + "1234567890-abcdefghij",
        "Stripe live key": "sk" + "_live_" + "abcdefghijklmnop1234",
        "Anthropic API key": "sk" + "-ant-" + "api03-abcdefghijklmnopqrstuv",
        "private key block": "-----BEGIN " + "RSA PRIVATE KEY-----",
    }

    def test_each_pattern_fails_and_never_prints_the_value(self):
        for label, value in self.FAKES.items():
            r = self.repo()
            r.write({"src/config.py": f'TOKEN = "{value}"\n'})
            found = errors(r.check("bob"), "secrets")
            self.assertTrue(found, label)
            self.assertNotIn(value, json.dumps([f.to_dict() for f in found]))

    def test_secrets_fail_even_for_owners(self):
        r = self.repo()
        r.write({"src/config.py": f'KEY = "{self.FAKES["AWS access key id"]}"\n'})
        self.assertTrue(errors(r.check("alice"), "secrets"))

    def test_generic_assignment(self):
        r = self.repo()
        r.write({"src/a.py": 'password = "' + "hunter2hunter2hunter2" + '"\n'})
        self.assertTrue(errors(r.check("bob"), "secrets"))

    def test_placeholders_and_short_values_pass(self):
        r = self.repo()
        r.write({"src/a.py": 'password = "your-password-here"\napi_key = "<API_KEY>"\ntoken = "${TOKEN}"\nsecret = "abc"\n'})
        self.assertEqual(errors(r.check("bob"), "secrets"), [])

    def test_removed_secret_lines_do_not_fail(self):
        files = dict(BASE_FILES)
        files["src/old.py"] = f'K = "{self.FAKES["AWS access key id"]}"\n'
        r = self.repo(files)
        r.write({"src/old.py": "K = None\n"})
        self.assertEqual(errors(r.check("bob"), "secrets"), [])

    def test_the_repo_itself_contains_no_secret_patterns(self):
        root = Path(ck.__file__).resolve().parents[1]
        if not (root / ".git").exists():
            self.skipTest("not running inside a git checkout")
        files = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True).stdout.split("\n")
        hits = []
        for rel in files:
            if not rel or rel.endswith((".svg", ".png", ".gif", ".lock")):
                continue
            p = root / rel
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            change = ck.Change(rel, "A", added=list(enumerate(text.split("\n"), 1)))
            hits += [f"{f.path}:{f.line}" for f in ck.check_secrets([change], ck.Context(cfg=None, author="x"))]
        self.assertEqual(hits, [])


class LockAndPinTests(CheckTestCase):
    def test_stale_lock_alarm_fails(self):
        r = self.repo()
        r.write({"src/app.py": "x = 1\n"})
        found = r.check("bob", lock=lambda: {"held": True, "alarm": True})
        self.assertTrue(errors(found, "lock"))

    def test_fresh_or_absent_lock_passes(self):
        for st in ({"held": True, "alarm": False}, {"held": False}):
            r = self.repo()
            r.write({"src/app.py": "x = 1\n"})
            self.assertEqual(errors(r.check("bob", lock=lambda st=st: st), "lock"), [])

    def test_unreadable_lock_is_a_warning_not_a_failure(self):
        r = self.repo()
        r.write({"src/app.py": "x = 1\n"})

        def boom():
            raise RuntimeError("network down")
        found = r.check("bob", lock=boom)
        self.assertEqual(errors(found, "lock"), [])
        self.assertTrue(warnings(found, "lock"))

    def test_pin_must_be_a_full_sha(self):
        for bad in ("main", "v0.1.0", "abc1234", "A" * 40, "a" * 39):
            files = dict(BASE_FILES)
            files[".laneguard/plugin.lock"] = f"repo: x/y\nsha: {bad}\n"
            r = self.repo(files)
            r.write({"src/app.py": "x = 1\n"})
            self.assertTrue(errors(r.check("alice"), "engine-pin"), bad)

    def test_missing_pin_fails(self):
        files = {k: v for k, v in BASE_FILES.items() if k != ".laneguard/plugin.lock"}
        r = self.repo(files)
        r.write({"src/app.py": "x = 1\n"})
        self.assertTrue(errors(r.check("alice"), "engine-pin"))

    def test_invalid_head_config_fails(self):
        r = self.repo()
        r.write({".laneguard/config.yaml": CONFIG.replace("mode: propose\nlanes", "mode: yolo\nlanes")})
        self.assertTrue(errors(r.check("alice"), "config"))


class LaneScopeTests(CheckTestCase):
    def test_lane_pr_inside_owns_passes(self):
        r = self.repo()
        r.write({"PROJECT_STATE.md": "next: x\n"})
        self.assertEqual(errors(r.check("bot", labels=["laneguard"]), "lane-scope"), [])

    def test_outside_owns_without_issue_fails(self):
        r = self.repo()
        r.write({"src/app.py": "x = 1\n"})
        found = errors(r.check("bot", labels=["laneguard"]), "lane-scope")
        self.assertEqual(len(found), 1)
        self.assertIn("no linked issue", found[0].message)

    def test_outside_owns_with_trusted_issue_passes(self):
        r = self.repo()
        r.write({"src/app.py": "x = 1\n"})
        found = r.check("bot", labels=["laneguard"], linked=[12], trust=lambda n: {"trusted": n == 12})
        self.assertEqual(errors(found, "lane-scope"), [])

    def test_outside_owns_with_untrusted_issue_fails(self):
        r = self.repo()
        r.write({"src/app.py": "x = 1\n"})
        found = r.check("bot", labels=["laneguard"], linked=[13], trust=lambda n: {"trusted": False})
        self.assertTrue(errors(found, "lane-scope"))

    def test_trust_lookup_failure_fails_closed(self):
        r = self.repo()
        r.write({"src/app.py": "x = 1\n"})

        def boom(n):
            raise RuntimeError("api down")
        self.assertTrue(errors(r.check("bot", labels=["laneguard"], linked=[12], trust=boom), "lane-scope"))

    def test_two_lane_labels_fail(self):
        r = self.repo()
        r.write({"PROJECT_STATE.md": "x\n"})
        self.assertTrue(errors(r.check("bot", labels=["laneguard", "laneguard-security"]), "lane-scope"))

    def test_security_lane_owns_docs_security(self):
        r = self.repo()
        r.write({"docs/security/new.md": "x\n"})
        self.assertEqual(errors(r.check("bot", labels=["laneguard-security"]), "lane-scope"), [])

    def test_unlabelled_pr_is_not_lane_checked(self):
        r = self.repo()
        r.write({"src/app.py": "x = 1\n"})
        self.assertEqual(errors(r.check("bob"), "lane-scope"), [])

    def test_link_parsing(self):
        self.assertEqual(ck.linked_issues_from_body("Closes #12, fixes acme/demo#7 and resolves #12"), [7, 12])
        self.assertEqual(ck.linked_issues_from_body("see #9"), [])


class BootstrapAndCliTests(CheckTestCase):
    def test_no_base_config_runs_secret_scan_only(self):
        files = {"README.md": "hi\n"}
        r = self.repo(files)
        r.write({".laneguard/config.yaml": CONFIG, ".laneguard/plugin.lock": f"sha: {SHA}\n"})
        found = r.check("alice")
        self.assertEqual(errors(found), [])
        self.assertTrue(warnings(found, "bootstrap"))

    def test_bootstrap_still_catches_secrets(self):
        r = self.repo({"README.md": "hi\n"})
        r.write({"src/a.py": 'K = "' + "AK" + "IA" + 'ABCDEFGHIJKLMNOP"\n', ".laneguard/plugin.lock": f"sha: {SHA}\n"})
        self.assertTrue(errors(r.check("alice"), "secrets"))

    def cli(self, r, *extra):
        head = r.commit()
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = ck.main(["--repo", r.dir, "--base", r.base, "--head", head, "--offline", *extra])
        return code, buf.getvalue()

    def test_cli_exit_codes_and_report(self):
        r = self.repo()
        r.write({".claude/settings.json": '{"x": 1}\n'})
        code, out = self.cli(r, "--author", "bob")
        self.assertEqual(code, 1)
        self.assertIn("FAILED", out)
        self.assertIn(".claude/settings.json", out)

    def test_cli_pass(self):
        r = self.repo()
        r.write({"src/app.py": "x = 1\n"})
        code, out = self.cli(r, "--author", "bob")
        self.assertEqual(code, 0)
        self.assertIn("PASSED", out)

    def test_cli_json(self):
        r = self.repo()
        r.write({"src/app.py": "x = 1\n"})
        code, out = self.cli(r, "--author", "bob", "--json")
        self.assertTrue(json.loads(out)["passed"])

    def test_cli_pr_body_links_feed_the_lane_scope_check(self):
        r = self.repo()
        r.write({"src/app.py": "x = 1\n"})
        body = Path(r.dir) / "body.txt"
        body.write_text("Closes #12\n")
        code, out = self.cli(r, "--author", "bot", "--labels", "laneguard", "--pr-body-file", str(body))
        # offline: the link cannot be verified, so the lane PR fails closed
        self.assertEqual(code, 1)
        self.assertIn("could not be verified offline", out)

    def test_cli_bad_revision_exits_2(self):
        r = self.repo()
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = ck.main(["--repo", r.dir, "--base", "nope", "--head", "nope2", "--author", "bob", "--offline"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()


class BaseConfigForgeTests(CheckTestCase):
    def test_online_forge_is_built_from_base_commit_config(self):
        """Issue #10: a PR that rewrites owners:/repo: must not change who the checker treats as owner."""
        import forge as fg
        r = self.repo()
        base_cfg = lc._merge_defaults(lc.loads(CONFIG))
        r.write({".laneguard/config.yaml": CONFIG.replace("owners: [alice]", "owners: [mallory]")})
        head = r.commit()
        seen = {}
        real = fg.Forge

        class Spy(real):
            def __init__(self, repo, owners, *a, **k):
                seen["repo"], seen["owners"] = repo, list(owners)
                super().__init__(repo, owners, *a, transport=object(), **k)
        fg.Forge = Spy
        try:
            ck.build_context(r.dir, r.base, head, "bob", "User", (), (), offline=False)
        finally:
            fg.Forge = real
        self.assertEqual(seen.get("owners"), base_cfg["owners"])
        self.assertNotIn("mallory", seen.get("owners", []))
