import random
import unittest

from randomize_core import clamp, enum_items_in_range, ordered_bounds, random_scalar, random_value


class RandomizeCoreTests(unittest.TestCase):
    def test_ordered_bounds_accepts_reversed_input(self):
        self.assertEqual(ordered_bounds(5, -2), (-2, 5))

    def test_clamp(self):
        self.assertEqual(clamp(-3, 0, 10), 0)
        self.assertEqual(clamp(11, 0, 10), 10)
        self.assertEqual(clamp(4, 0, 10), 4)

    def test_seed_is_reproducible(self):
        first = random_value("FLOAT", random.Random(42), array_length=3, minimum=-2, maximum=2)
        second = random_value("FLOAT", random.Random(42), array_length=3, minimum=-2, maximum=2)
        self.assertEqual(first, second)

    def test_vector_uses_per_component_bounds(self):
        value = random_value(
            "FLOAT",
            random.Random(42),
            array_length=3,
            minimum=(1.0, 10.0, 100.0),
            maximum=(2.0, 20.0, 200.0),
        )
        self.assertTrue(1.0 <= value[0] <= 2.0)
        self.assertTrue(10.0 <= value[1] <= 20.0)
        self.assertTrue(100.0 <= value[2] <= 200.0)

    def test_integer_range_is_inclusive(self):
        values = {
            random_scalar("INT", random.Random(seed), minimum=2, maximum=3)
            for seed in range(20)
        }
        self.assertEqual(values, {2, 3})

    def test_boolean_probability_extremes(self):
        self.assertTrue(random_scalar("BOOLEAN", random.Random(1), probability=1.0))
        self.assertFalse(random_scalar("BOOLEAN", random.Random(1), probability=0.0))

    def test_enum_flag_returns_valid_subset(self):
        items = ("A", "B", "C")
        value = random_scalar("ENUM", random.Random(7), enum_items=items, enum_flag=True)
        self.assertIsInstance(value, set)
        self.assertTrue(value.issubset(items))

    def test_enum_index_range_is_inclusive(self):
        items = ("A", "B", "C", "D")
        self.assertEqual(enum_items_in_range(items, 1, 2), ("B", "C"))
        self.assertEqual(enum_items_in_range(items, 2, 1), ("B", "C"))

    def test_enum_index_range_supports_negative_and_clamped_indices(self):
        items = ("A", "B", "C", "D")
        self.assertEqual(enum_items_in_range(items, 0, -1), items)
        self.assertEqual(enum_items_in_range(items, -2, -1), ("C", "D"))
        self.assertEqual(enum_items_in_range(items, -100, 100), items)

    def test_unsupported_type_raises(self):
        with self.assertRaises(ValueError):
            random_scalar("STRING", random.Random(0))


if __name__ == "__main__":
    unittest.main()
