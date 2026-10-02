import os

PUBLIC_DIR = os.path.join(os.path.dirname(__file__), "..", "public")


def read_public_file(relative_name):
    # SEEDED VULN VA-2: path traversal; '../' escapes PUBLIC_DIR.
    path = os.path.join(PUBLIC_DIR, relative_name)
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()
