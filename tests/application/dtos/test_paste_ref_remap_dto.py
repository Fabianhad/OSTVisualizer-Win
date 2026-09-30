import unittest
from ost_visualizer.application.dtos.paste_ref_remap_dto import PasteRefRemap


class PasteRefRemapTests(unittest.TestCase):
    def test_annotation_projection_matches_persisted_reference_remaps(self):
        remap = PasteRefRemap(
            takeoff_uids={"old-from": "new-from"},
            namedview_uids={"old-view": "new-view"},
        )
        properties = remap.remap_annotation_properties(
            {
                "BidTakeoffFromUID": "old-from",
                "BidTakeoffToUID": "missing-takeoff",
                "BidPageViewUID": "old-view",
                "Text": "kept",
            }
        )
        self.assertEqual(
            properties,
            {
                "BidTakeoffFromUID": "new-from",
                "BidPageViewUID": "new-view",
                "Text": "kept",
            },
        )

    def test_existing_named_view_reference_is_retained_without_a_remap(self):
        properties = PasteRefRemap().remap_annotation_properties(
            {"BidPageViewUID": "existing-view"}
        )
        self.assertEqual(properties, {"BidPageViewUID": "existing-view"})

    def test_empty_reference_values_match_rehydrated_model_shape(self):
        properties = PasteRefRemap().remap_annotation_properties(
            {
                "BidTakeoffFromUID": "",
                "BidTakeoffToUID": "0",
                "BidPageViewUID": "",
            }
        )
        self.assertEqual(properties, {"BidPageViewUID": None})


if __name__ == "__main__":
    unittest.main()
