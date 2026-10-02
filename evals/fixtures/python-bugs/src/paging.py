"""Tiny pagination and statistics helpers (seeded with bugs for the Laneguard eval suite)."""


def page(items, page_number, page_size):
    """Return the items on a 1-indexed page."""
    start = page_number * page_size  # SEEDED BUG PY-1: off-by-one, pages are 1-indexed
    return items[start:start + page_size]


def page_count(total, page_size):
    """Number of pages needed for `total` items."""
    return total // page_size  # SEEDED BUG PY-2: drops the final partial page
