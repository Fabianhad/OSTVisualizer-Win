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
        self.assertTrue(
            condition_changes_require_mesh_refresh([], ["create", "update"])
        )
        self.assertTrue(condition_changes_require_mesh_refresh([], ["unknown"]))


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
        self.assertTrue(
            condition_changes_require_plan_refresh([], ["reorder", "update"])
        )
        self.assertTrue(condition_changes_require_plan_refresh([], ["unknown"]))


MESH_FIELDS = (
    "color_fill condition_type depth display_size drop_run drop_value height is_top "
    "layer_uid pattern rise run shape thickness width z_value"
).split()
PLAN_ONLY_FIELDS = (
    "backout calc_type1 calc_type2 calc_type3 display_dimension display_grid_while_drawing "
    "display_name gap grid grid_size1 grid_size2 is_curved_segment name round_quantity "
    "round_up spacing trim uom1 uom2 uom3"
).split()
METADATA_FIELDS = "cdn_type_uid condition_folder condition_type_catalog folder_uid notes ref_no".split()


class ConditionFieldClassificationTableTests(unittest.TestCase):
    def test_every_classified_field_has_the_documented_mesh_and_plan_impact_on_its_own(self):
        for field in MESH_FIELDS:
            with self.subTest(mesh_field=field):
                self.assertIs(condition_changes_require_mesh_refresh([field]), True)
                self.assertIs(condition_changes_require_plan_refresh([field]), True)
        for field in PLAN_ONLY_FIELDS:
            with self.subTest(plan_field=field):
                self.assertIs(condition_changes_require_mesh_refresh([field]), False)
                self.assertIs(condition_changes_require_plan_refresh([field]), True)
        for field in METADATA_FIELDS:
            with self.subTest(metadata_field=field):
                self.assertIs(condition_changes_require_mesh_refresh([field]), False)
                self.assertIs(condition_changes_require_plan_refresh([field]), False)

    def test_classification_sets_are_disjoint_and_complete_for_the_stored_columns(self):
        names = MESH_FIELDS + PLAN_ONLY_FIELDS + METADATA_FIELDS
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(names), 16 + 20 + 6)

    def test_a_mixed_change_set_uses_the_most_demanding_member(self):
        self.assertIs(condition_changes_require_mesh_refresh(["name", "notes", "width"]), True)
        self.assertIs(condition_changes_require_mesh_refresh(["name", "notes"]), False)
        self.assertIs(condition_changes_require_plan_refresh(["notes", "ref_no", "name"]), True)
        self.assertIs(condition_changes_require_plan_refresh(["notes", "ref_no", "folder_uid"]), False)
        self.assertIs(condition_changes_require_mesh_refresh(["name", "brand_new"]), True)
        self.assertIs(condition_changes_require_plan_refresh(["notes", "brand_new"]), True)

    def test_blank_field_names_and_operations_are_ignored_and_inputs_may_be_any_iterable(self):
        self.assertIs(condition_changes_require_mesh_refresh(["", None, "notes"]), False)
        self.assertIs(condition_changes_require_plan_refresh(["", None, "notes"]), False)
        self.assertIs(condition_changes_require_mesh_refresh(iter(["width"])), True)
        self.assertIs(condition_changes_require_mesh_refresh(["notes"], ["", None]), False)
        self.assertIs(condition_changes_require_plan_refresh(["notes"], iter(["", None])), False)
        self.assertIs(condition_changes_require_mesh_refresh(["notes"], ["update"]), False)

    def test_operations_only_matter_when_no_fields_are_named_except_delete_and_create_for_plan(self):
        self.assertIs(condition_changes_require_mesh_refresh(["notes"], ["create"]), False)
        self.assertIs(condition_changes_require_mesh_refresh(["notes"], ["reorder"]), False)
        self.assertIs(condition_changes_require_mesh_refresh([], ["create", "reorder"]), False)
        self.assertIs(condition_changes_require_mesh_refresh([], ["reorder"]), False)
        self.assertIs(condition_changes_require_mesh_refresh([], ["delete"]), True)
        self.assertIs(condition_changes_require_plan_refresh(["notes"], ["reorder"]), False)
        self.assertIs(condition_changes_require_plan_refresh(["notes"], ["update"]), False)
        self.assertIs(condition_changes_require_plan_refresh([], ["reorder", "reorder"]), False)
        self.assertIs(condition_changes_require_plan_refresh([], ["create"]), True)
        self.assertIs(condition_changes_require_plan_refresh([], ["delete"]), True)
        self.assertIs(condition_changes_require_plan_refresh([], ["update"]), True)
