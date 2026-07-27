import unittest
from types import SimpleNamespace
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import (
    Takeoff,
    find_takeoff_parent_cycle_uids,
)
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from ost_visualizer.infrastructure.mdb.components.bid_data_reader import (
    BidDataReaderMixin,
)
from ost_visualizer.infrastructure.sql.reader import SqlProjectReader


class _Cursor:
    def __init__(self, columns, rows):
        self.description = [(column,) for column in columns]
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, *_args):
        return self

    def fetchall(self):
        return list(self._rows)


class _Connection:
    def __init__(self, columns, rows):
        self._columns = columns
        self._rows = rows

    def cursor(self):
        return _Cursor(self._columns, self._rows)


class _Schema:
    def __init__(self, columns):
        self._columns = set(columns)

    def get_columns(self, _table):
        return set(self._columns)

    def optional_column(self, *_args):
        return False


def _hydrate(reader):
    columns = (
        "UID",
        "BidUID",
        "BidConditionUID",
        "BidPageUID",
        "BidAreaUID",
        "Position",
        "Rotation",
        "Curve",
        "ParentUID",
        "IsNegativeQuantity",
        "FontName",
        "FontColor",
        "FontSize",
        "FontBold",
        "FontItalic",
        "FontUnderline",
        "NameFontName",
        "NameFontColor",
        "NameFontSize",
        "NameFontBold",
        "NameFontItalic",
        "NameFontUnderline",
    )
    row = (
        4485,
        7,
        10,
        20,
        None,
        b"1;2;3;4\n",
        15.0,
        0,
        None,
        1,
        "Arial",
        255,
        -72,
        1,
        0,
        1,
        "Calibri",
        128,
        -48,
        0,
        1,
        0,
    )
    return reader._parse_bid_takeoffs_for_bid(
        _Connection(columns, [row]), "7", _Schema(columns)
    )[0][0]


class TakeoffHydrationContractTests(unittest.TestCase):
    def test_access_reader_builds_complete_takeoff_contract(self):
        takeoff = _hydrate(BidDataReaderMixin())
        self.assertTrue(takeoff.has_valid_contract())
        self.assertEqual(takeoff.uid, "4485")
        self.assertEqual(takeoff.parent_uid, "0")
        self.assertEqual(takeoff.position, [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(takeoff.dimension_font_size, 72)
        self.assertEqual(takeoff.name_font_size, 48)

    def test_sql_reader_uses_the_same_complete_takeoff_contract(self):
        takeoff = _hydrate(SqlProjectReader.__new__(SqlProjectReader))
        self.assertTrue(takeoff.has_valid_contract())
        self.assertEqual(takeoff.condition_uid, "10")
        self.assertFalse(hasattr(takeoff, "layer_uid"))

    def test_layer_usage_follows_takeoff_condition_contract(self):
        takeoff = Takeoff(uid="4485", condition_uid="10", page_uid="20")
        annotation = BidAnnotation(
            uid="99", annotation_type="rectangle", page_uid="20", layer_uid="30"
        )
        model = SimpleNamespace(
            bid_conditions={"10": Condition(uid="10", layer_uid="25")},
            get_all_takeoffs=lambda: [takeoff],
            get_all_annotations=lambda: [annotation],
        )
        self.assertEqual(
            ProjectDataService(model).get_layer_uids_in_use(), {"25", "30"}
        )

    def test_takeoff_contract_rejects_missing_declared_field(self):
        takeoff = Takeoff(uid="4485", condition_uid="10", page_uid="20")
        del takeoff.uid
        self.assertFalse(takeoff.has_valid_contract())

    def test_takeoff_contract_rejects_bool_as_numeric_storage(self):
        takeoff = Takeoff(
            uid="4485",
            condition_uid="10",
            page_uid="20",
            rotation=True,
        )
        self.assertFalse(takeoff.has_valid_contract())

    def test_takeoff_contract_rejects_non_finite_numeric_storage(self):
        for field_name, value in (
            ("position", [1.0, float("nan"), 3.0, 4.0]),
            ("position", [1.0, float("inf"), 3.0, 4.0]),
            ("rotation", float("-inf")),
            ("rotation", 10**1000),
        ):
            with self.subTest(field_name=field_name, value=value):
                takeoff = Takeoff(
                    uid="4485",
                    condition_uid="10",
                    page_uid="20",
                )
                setattr(takeoff, field_name, value)
                self.assertFalse(takeoff.has_valid_contract())

    def test_takeoff_parent_cycle_detection_is_order_independent(self):
        self.assertEqual(
            find_takeoff_parent_cycle_uids(
                {"32": "31", "30": "0", "31": "32", "33": "32"}
            ),
            {"31", "32"},
        )


if __name__ == "__main__":
    unittest.main()
