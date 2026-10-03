import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import forge as fg  # noqa: E402
import forge_read as fr  # noqa: E402

REPO = "acme/demo"
R = f"/repos/{REPO}"


class FakeTransport:
    def __init__(self, routes=None):
        self.routes = routes or {}
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        bare = (method, path.split("?", 1)[0])
        if bare in self.routes:
            return fg.Response(200, {"Date": "Fri, 02 Oct 2026 12:00:00 GMT"}, self.routes[bare])
        return fg.Response(404, {}, {"message": "Not Found"})


def ro(routes=None):
    return fr.ReadOnlyForge(REPO, ["alice"], 1, transport=FakeTransport(routes or {}))


class ReadOnlyForgeTests(unittest.TestCase):
    def test_every_write_method_is_refused_before_any_request(self):
        f = ro()
        attempts = [
            lambda: f.comment(1, "hi"), lambda: f.label_add(1, "x"), lambda: f.label_remove(1, "x"),
            lambda: f.create_issue("t", "b"), lambda: f.create_pr("h", "b", "t", "b"),
            lambda: f.claim(1, "dev", "run-1"),
        ]
        for attempt in attempts:
            with self.assertRaises(fg.ForgeDenied):
                attempt()
        self.assertEqual([c for c in f.t.calls if c[0] != "GET"], [])

    def test_reads_still_work(self):
        f = ro({("GET", f"{R}/issues/5"): {"number": 5, "title": "t", "body": "b", "user": {"login": "alice", "type": "User"},
                                           "labels": [], "created_at": "2026-10-01T00:00:00Z", "updated_at": "2026-10-01T00:00:00Z"},
                ("GET", f"{R}/issues/5/comments"): [], ("GET", f"{R}/issues/5/events"): [], ("GET", f"{R}/issues/5/timeline"): []})
        got = f.read_issue(5)
        self.assertEqual(got["number"], 5)


class CliTests(unittest.TestCase):
    def run_cli(self, argv, forge=None):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = fr.main(argv, forge=forge)
        return rc, out.getvalue(), err.getvalue()

    def test_write_subcommand_is_rejected_without_touching_the_forge(self):
        f = ro()
        for argv in (["write", "merge", "--number", "1"],
                     ["write", "review-status", "--sha", "x", "--verdict", "APPROVE", "--lane", "dev"],
                     ["write", "claim", "--number", "1", "--lane", "dev", "--run-id", "r"],
                     ["--root", ".", "write", "comment", "--number", "1", "--body-file", "/dev/null"]):
            rc, out, err = self.run_cli(argv, forge=f)
            self.assertEqual(rc, 2, argv)
            self.assertIn("not a read command", err)
        self.assertEqual(f.t.calls, [])

    def test_read_subcommands_dispatch(self):
        f = ro({("GET", "/rate_limit"): {}})
        rc, out, _ = self.run_cli(["now"], forge=f)
        self.assertEqual(rc, 0)
        self.assertIn("2026-10-02T12:00:00Z", out)

    def test_plain_forge_is_wrapped_read_only(self):
        plain = fg.Forge(REPO, ["alice"], 1, transport=FakeTransport({("GET", "/rate_limit"): {}}))
        rc, out, _ = self.run_cli(["now"], forge=plain)
        self.assertEqual(rc, 0)
        # and a write via the CLI is still impossible
        rc, _, err = self.run_cli(["write", "merge", "--number", "1"], forge=plain)
        self.assertEqual(rc, 2)

    def test_script_has_no_write_commands_in_its_usage(self):
        self.assertNotIn("write", " ".join(fr.READ_COMMANDS))
        self.assertNotIn("forge_read.py write", fr.__doc__)


if __name__ == "__main__":
    unittest.main()
