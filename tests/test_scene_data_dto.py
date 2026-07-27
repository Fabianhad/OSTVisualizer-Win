import unittest

from ost_visualizer.application.dtos.scene_data_dto import SceneData, ScenePageEntry


class SceneDataDtoTests(unittest.TestCase):
    def test_page_plane_keys_are_optional_without_weakening_page_identity(self):
        self.assertEqual(
            ScenePageEntry.__optional_keys__,
            {
                "plane_x",
                "plane_y",
                "plane_z",
                "plane_width",
                "plane_height",
                "plane_flip_u",
                "plane_flip_v",
            },
        )
        self.assertTrue(
            {
                "uid",
                "label",
                "name",
                "sheet_no",
                "sequence",
                "width",
                "height",
                "page_width",
                "page_height",
                "image_layer_uid",
                "visible",
                "pdf_document_uid",
                "pdf_page_index",
            }.issubset(ScenePageEntry.__required_keys__)
        )

    def test_scene_viewer_core_is_required_and_extensions_are_optional(self):
        self.assertEqual(
            SceneData.__required_keys__,
            {"title", "geometries", "camera", "bounds"},
        )
        self.assertTrue(
            {
                "layers",
                "conditions",
                "areas",
                "page_image_layer",
                "pages",
                "active_page_uid",
                "selected_page_uids",
                "pdf_documents",
                "takeoffs_2d",
                "elevation_callouts",
                "display_modes",
            }.issubset(SceneData.__optional_keys__)
        )


if __name__ == "__main__":
    unittest.main()
