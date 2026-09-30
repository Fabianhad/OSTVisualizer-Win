import unittest
from ost_visualizer.application.condition_change_impact import (
    condition_changes_require_mesh_refresh,
    condition_changes_require_plan_refresh,
)


class ConditionChangesRequireMeshRefreshTests(unittest.TestCase):
    def test_unknown_fields_are_conservative_but_known_metadata_is_not(self):
        for fields, expected in (
            (["name", "uom1", "notes"], False),
            (["width"], True),
            (["new_unclassified_property"], True),
            (["name", "width"], True),
        ):
            with self.subTest(fields=fields):
                self.assertEqual(
                    condition_changes_require_mesh_refresh(fields), expected
                )

    def test_delete_overrides_metadata_and_empty_reorder_does_not_rebuild(self):
        self.assertTrue(condition_changes_require_mesh_refresh(["notes"], ["delete"]))
        self.assertFalse(condition_changes_require_mesh_refresh([], ["reorder"]))
        self.assertFalse(condition_changes_require_mesh_refresh([], ["create"]))
        self.assertTrue(condition_changes_require_mesh_refresh([], ["update"]))
        self.assertTrue(condition_changes_require_mesh_refresh([]))


class ConditionChangesRequirePlanRefreshTests(unittest.TestCase):
    def test_label_and_quantity_changes_refresh_but_folder_metadata_does_not(self):
        self.assertFalse(
            condition_changes_require_plan_refresh(["folder_uid", "ref_no"])
        )
        self.assertTrue(condition_changes_require_plan_refresh(["name"]))
        self.assertTrue(condition_changes_require_plan_refresh(["uom1"]))
        self.assertTrue(condition_changes_require_plan_refresh(["unclassified"]))

    def test_create_and_delete_override_narrow_metadata(self):
        for operation in ("create", "delete"):
            with self.subTest(operation=operation):
                self.assertTrue(
                    condition_changes_require_plan_refresh(["notes"], [operation])
                )
        self.assertFalse(condition_changes_require_plan_refresh([], ["reorder"]))
        self.assertTrue(condition_changes_require_plan_refresh([]))
