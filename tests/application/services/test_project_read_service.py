import unittest
from copy import deepcopy
from unittest.mock import create_autospec
from ost_visualizer.application.interfaces.i_mdb_reader import IMdbReader
from ost_visualizer.application.services.project_read_service import ProjectReadService
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.cdn_type import CdnType
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.condition_folder import BidConditionFolder
from ost_visualizer.domain.entities.cover_sheet import CoverSheetData, JobStatus
from ost_visualizer.domain.entities.employee import Employee, PayClass
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.domain.services.uom_service import (
    UOM_EACH,
    UOM_INCHES,
    UOM_M,
    UOM_MM,
    UOM_LINEAR_FEET,
    UOM_LINEAR_YARDS,
)


def _layer(uid: str, name: str, sequence: int, *, is_template: bool = True) -> BidLayer:
    return BidLayer(
        uid=uid,
        bid_uid="bid-1",
        name=name,
        show=True,
        sequence=sequence,
        is_template=is_template,
        is_locked=is_template,
    )


class ProjectReadServiceTests(unittest.TestCase):
    def setUp(self):
        self.reader = create_autospec(IMdbReader, instance=True, spec_set=True)
        self.service = ProjectReadService(self.reader)

    def test_merged_bid_layers_hide_comments_layer_from_project_ui(self):
        image = _layer("image", "Image", 0)
        default = _layer("default", "Default", 2)
        override = _layer("bid-image", "IMAGE", 4, is_template=False)
        custom = _layer("custom", "Custom", 6, is_template=False)
        source = [
            custom,
            _layer("comments", "  CoMmEnTs  ", 3),
            override,
            default,
            image,
        ]
        before = deepcopy(source)
        self.reader.get_bid_layers_for_sidebar.return_value = source
        layers = self.service.get_merged_bid_layers("a.mdb", "bid-1")
        self.assertEqual(layers, [default, override, custom])
        for actual, expected in zip(layers, [default, override, custom]):
            self.assertIs(actual, expected)
        self.assertEqual(source, before)
        self.reader.get_bid_layers_for_sidebar.assert_called_once_with("a.mdb", "bid-1")
        self.assertEqual(len(self.reader.mock_calls), 1)

    def test_default_layers_keep_comments_layer(self):
        expected = [_layer("image", "Image", 0), _layer("comments", "Comments", 3)]
        self.reader.get_default_layers.return_value = expected
        self.assertIs(self.service.get_default_layers("a.mdb"), expected)
        self.assertEqual([layer.name for layer in expected], ["Image", "Comments"])
        self.reader.get_default_layers.assert_called_once_with("a.mdb")

    def test_bid_lock_lookup_preserves_authoritative_status_uid(self):
        self.reader.get_job_statuses.return_value = [
            JobStatus(uid="status-unlocked", name="Duplicate", locked=False),
            JobStatus(uid="status-locked", name="Duplicate", locked=True),
        ]
        self.assertTrue(self.service.is_bid_locked("a.mdb", "status-locked"))
        self.assertFalse(self.service.is_bid_locked("a.mdb", "status-unlocked"))
        self.assertEqual(self.reader.get_job_statuses.call_count, 2)
        self.reader.get_job_statuses.assert_called_with("a.mdb")

    def _reads(self):
        return [
            (
                self.service.get_cdn_types,
                self.reader.get_cdn_types,
                ("db",),
                {"1": CdnType("1", "Type")},
                {},
            ),
            (
                self.service.get_job_statuses,
                self.reader.get_job_statuses,
                ("db",),
                [JobStatus("1", "Open")],
                [],
            ),
            (
                self.service.get_cover_sheet_data,
                self.reader.get_cover_sheet_data,
                ("db", "7"),
                CoverSheetData("7", "1", "Job", "2", "Notes", "2026-09-30", "1", "J1"),
                None,
            ),
            (
                self.service.get_employee_uids_in_use,
                self.reader.get_employee_uids_in_use,
                ("db",),
                {"2"},
                set(),
            ),
            (
                self.service.get_condition_type_uids_in_use,
                self.reader.get_condition_type_uids_in_use,
                ("db",),
                {"1"},
                set(),
            ),
            (
                self.service.get_layer_uids_in_use,
                self.reader.get_layer_uids_in_use,
                ("db", "7"),
                {"3"},
                set(),
            ),
            (
                self.service.get_employees_and_pay_classes,
                self.reader.get_employees_and_pay_classes,
                ("db",),
                ([Employee("2")], [PayClass("4", "Worker")]),
                ([], []),
            ),
            (
                self.service.get_bid_areas,
                self.reader.get_bid_areas,
                ("db", "7"),
                [BidArea("5", "7", "", "Area", 0)],
                [],
            ),
            (
                self.service.get_settings_defaults,
                self.reader.get_settings_defaults,
                ("db",),
                {"MeasureBase": 1},
                {},
            ),
            (
                self.service.get_pages_with_takeoffs,
                self.reader.get_pages_with_takeoffs,
                ("db", "7"),
                {"21"},
                set(),
            ),
            (
                self.service.get_pages_with_delete_content,
                self.reader.get_pages_with_delete_content,
                ("db", "7"),
                {"22"},
                None,
            ),
        ]

    def test_optional_reads_forward_exact_scope_and_preserve_typed_results(self):
        for operation, reader, arguments, expected, _fallback in self._reads():
            with self.subTest(operation=operation.__name__):
                self.reader.reset_mock()
                reader.return_value = expected
                before = deepcopy(expected)
                self.assertIs(operation(*arguments), expected)
                self.assertEqual(expected, before)
                reader.assert_called_once_with(*arguments)
                self.assertEqual(len(self.reader.mock_calls), 1)

    def test_optional_read_failures_use_documented_empty_or_unknown_results(self):
        reads = self._reads() + [
            (
                self.service.get_default_layers,
                self.reader.get_default_layers,
                ("db",),
                [],
                [],
            ),
            (
                self.service.get_merged_bid_layers,
                self.reader.get_bid_layers_for_sidebar,
                ("db", "7"),
                [],
                [],
            ),
        ]
        for operation, reader, arguments, _expected, fallback in reads:
            with self.subTest(operation=operation.__name__):
                self.reader.reset_mock(side_effect=True)
                reader.side_effect = OSError("read unavailable")
                with self.assertLogs(
                    "ost_visualizer.application.services.project_read_service",
                    level="WARNING",
                ) as logs:
                    result = operation(*arguments)
                self.assertEqual(result, fallback)
                self.assertEqual(len(logs.records), 1)
                reader.assert_called_once_with(*arguments)
                self.assertEqual(len(self.reader.mock_calls), 1)
        # An empty, successful deletion-usage read is not the unknown/failure sentinel.
        self.reader.get_pages_with_delete_content.side_effect = None
        self.reader.get_pages_with_delete_content.return_value = set()
        self.assertEqual(self.service.get_pages_with_delete_content("db", "7"), set())

    def test_authoritative_family_and_master_usage_reads_propagate_failure(self):
        conditions = {"1": Condition("1")}
        folders = {"2": BidConditionFolder("2", name="Folder")}
        for operation, reader, arguments, expected in (
            (
                self.service.get_condition_family,
                self.reader.get_condition_family,
                ("db", "7"),
                (conditions, folders),
            ),
            (
                self.service.get_area_family,
                self.reader.get_area_family,
                ("db", "7"),
                [BidArea("3", "7", "", "Area", 0)],
            ),
            (
                self.service.get_master_data_uids_in_use,
                self.reader.get_master_data_uids_in_use,
                ("db", "employees"),
                {"4"},
            ),
        ):
            with self.subTest(operation=operation.__name__):
                self.reader.reset_mock(side_effect=True)
                reader.return_value = expected
                self.assertIs(operation(*arguments), expected)
                reader.assert_called_once_with(*arguments)
                self.reader.reset_mock()
                error = OSError("authoritative read incomplete")
                reader.side_effect = error
                with self.assertRaises(OSError) as raised:
                    operation(*arguments)
                self.assertIs(raised.exception, error)
                reader.assert_called_once_with(*arguments)
                self.assertEqual(len(self.reader.mock_calls), 1)

    def test_absent_status_skips_read_and_unknown_status_does_not_match_name(self):
        for status in (None, ""):
            self.assertIs(self.service.is_bid_locked("db", status), False)
        self.reader.get_job_statuses.assert_not_called()
        self.reader.get_job_statuses.return_value = [
            JobStatus("9", "missing", locked=True)
        ]
        self.assertIs(self.service.is_bid_locked("db", "missing"), False)
        self.assertIs(self.service.is_bid_locked("db", "9"), True)
        self.reader.get_job_statuses.return_value = []
        self.assertIs(self.service.is_bid_locked("db", "9"), False)

    def test_dimension_facade_uses_real_metric_and_imperial_formatting(self):
        self.assertEqual(self.service.display_to_inches("25.4", True), 1.0)
        self.assertEqual(self.service.display_to_inches("1' - 6\""), 18.0)
        self.assertIsNone(self.service.display_to_inches("not a dimension"))
        self.assertEqual(self.service.inches_to_display(1.0, True), "25.4")
        self.assertEqual(self.service.inches_to_display(18.0), "1' 6\"")
        self.assertEqual(self.reader.mock_calls, [])

    def test_uom_facade_preserves_calculation_and_measurement_system(self):
        self.assertEqual(self.service.get_uom_label(UOM_M), "m")
        self.assertEqual(
            self.service.get_valid_uoms_for_calc_type(1, True),
            [(UOM_M, "m"), (UOM_MM, "mm")],
        )
        self.assertEqual(
            self.service.get_valid_uoms_for_calc_type(1),
            [(UOM_LINEAR_FEET, "LF"), (UOM_LINEAR_YARDS, "LY"), (UOM_INCHES, "IN")],
        )
        self.assertEqual(
            self.service.get_valid_uoms_for_calc_type(2, True), [(UOM_EACH, "EA")]
        )
        linear = self.service.get_quantity_options_for_type(Condition.TYPE_LINEAR)
        area = self.service.get_quantity_options_for_type(Condition.TYPE_AREA)
        self.assertEqual(linear[0], (1, "Length"))
        self.assertEqual(area[0], (11, "Area"))
        self.assertEqual(self.reader.mock_calls, [])


if __name__ == "__main__":
    unittest.main()
