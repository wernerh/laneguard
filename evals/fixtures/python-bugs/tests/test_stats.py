import unittest

from src.stats import mean


class StatsTests(unittest.TestCase):
    def test_mean(self):
        self.assertEqual(mean([1, 2, 3]), 2)

    def test_mean_of_empty_is_zero(self):
        self.assertEqual(mean([]), 0.0)


if __name__ == "__main__":
    unittest.main()
