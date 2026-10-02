import unittest

from src.files import read_public_file
from src.render import greeting_html
from src.users import connect, find_user


class SecurityTests(unittest.TestCase):
    def test_sql_injection_returns_nothing(self):
        conn = connect()
        self.assertEqual(find_user(conn, "x' OR '1'='1"), [])

    def test_normal_lookup_still_works(self):
        conn = connect()
        self.assertEqual(find_user(conn, "alice"), [(1, "alice")])

    def test_path_traversal_is_rejected(self):
        with self.assertRaises((ValueError, PermissionError, FileNotFoundError)):
            read_public_file("../secret_marker.txt")

    def test_public_file_still_readable(self):
        self.assertEqual(read_public_file("hello.txt").strip(), "public file")

    def test_html_is_escaped(self):
        self.assertNotIn("<script>", greeting_html("<script>alert(1)</script>"))


if __name__ == "__main__":
    unittest.main()
