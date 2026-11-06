import sqlite3
import unittest
from ost_visualizer.infrastructure.mdb.components.sql_helpers import placeholders


class PlaceholdersTests(unittest.TestCase):
    def test_returns_one_comma_separated_marker_per_value(self):
        self.assertEqual(placeholders([]), "")
        self.assertEqual(placeholders([10]), "?")
        self.assertEqual(placeholders([10, 20]), "?,?")
        self.assertEqual(placeholders((1, 2, 3)), "?,?,?")
        self.assertEqual(placeholders(range(5)), "?,?,?,?,?")
        self.assertEqual(placeholders({"a", "b", "c", "d"}), "?,?,?,?")

    def test_markers_depend_on_count_not_on_value_content(self):
        self.assertEqual(placeholders(["x, y", None, "?"]), "?,?,?")
        self.assertEqual(placeholders(["only"]), "?")

    def test_has_no_whitespace_and_counts_exactly_n_markers(self):
        for count in (0, 1, 2, 7, 50):
            with self.subTest(count=count):
                result = placeholders(list(range(count)))
                self.assertEqual(result.count("?"), count)
                self.assertEqual(result.count(","), max(count - 1, 0))
                self.assertEqual(len(result), max(2 * count - 1, 0))

    def test_unsized_iterables_are_rejected_instead_of_consumed(self):
        values = (value for value in (1, 2, 3))
        with self.assertRaises(TypeError):
            placeholders(values)
        self.assertEqual(list(values), [1, 2, 3])

    def test_generated_marker_list_binds_the_values_in_a_real_in_clause(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.execute("CREATE TABLE Item (UID INTEGER PRIMARY KEY, Name TEXT)")
        connection.executemany(
            "INSERT INTO Item (UID, Name) VALUES (?, ?)",
            [(1, "a"), (2, "b"), (3, "c"), (4, "d")],
        )
        wanted = [4, 2, 99]
        rows = connection.execute(
            f"SELECT UID, Name FROM Item WHERE UID IN ({placeholders(wanted)}) "
            "ORDER BY UID",
            wanted,
        ).fetchall()
        self.assertEqual(rows, [(2, "b"), (4, "d")])
