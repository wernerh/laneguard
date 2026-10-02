import unittest

from src.paging import page, page_count


class PagingTests(unittest.TestCase):
    def test_first_page_is_one_indexed(self):
        self.assertEqual(page([1, 2, 3, 4, 5], 1, 2), [1, 2])

    def test_last_partial_page(self):
        self.assertEqual(page([1, 2, 3, 4, 5], 3, 2), [5])

    def test_page_count_rounds_up(self):
        self.assertEqual(page_count(5, 2), 3)

    def test_page_count_exact(self):
        self.assertEqual(page_count(4, 2), 2)


if __name__ == "__main__":
    unittest.main()
