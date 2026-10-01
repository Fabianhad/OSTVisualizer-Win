import unittest
from ost_visualizer.application.dtos.paste_ref_remap_dto import PasteRefRemap


class PasteRefRemapTests(unittest.TestCase):
    def test_annotation_projection_matches_persisted_reference_remaps(self):
        remap = PasteRefRemap(
            takeoff_uids={"old-from": "new-from"},
            namedview_uids={"old-view": "new-view"},
        )
        original = {
            "BidTakeoffFromUID": "old-from",
            "BidTakeoffToUID": "missing-takeoff",
            "BidPageViewUID": "old-view",
            "Text": "kept",
        }
        properties = remap.remap_annotation_properties(original)
        self.assertIsNot(properties, original)
        self.assertEqual(
            original,
            {
                "BidTakeoffFromUID": "old-from",
                "BidTakeoffToUID": "missing-takeoff",
                "BidPageViewUID": "old-view",
                "Text": "kept",
            },
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
        for sentinel in (None, "", "0", 0):
            with self.subTest(sentinel=sentinel):
                properties = PasteRefRemap().remap_annotation_properties(
                    {
                        "BidTakeoffFromUID": sentinel,
                        "BidTakeoffToUID": sentinel,
                        "BidPageViewUID": sentinel,
                    }
                )
                self.assertEqual(properties, {"BidPageViewUID": None})
        self.assertEqual(
            PasteRefRemap().remap_annotation_properties({"Text": "kept"}),
            {"Text": "kept"},
        )


if __name__ == "__main__":
    unittest.main()
