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


class SceneDataContractTests(unittest.TestCase):
    def test_every_scene_typed_dict_pins_its_exact_keys_and_value_types(self):
        from typing import Dict, List, get_type_hints
        from ost_visualizer.application.dtos import scene_data_dto as module

        expected = {
            "SceneCameraConfig": {"position": List[float], "target": List[float]},
            "SceneBoundsConfig": {"min": List[float], "max": List[float]},
            "SceneDisplayModesConfig": {
                "synced": bool,
                "mode_3d": str,
                "mode_2d": str,
            },
            "SceneViewOptionsConfig": {"edges": bool, "tower_crane": bool},
            "SceneTowerCranePlacement": {
                "position": List[float],
                "rotation_y": float,
                "tint": List[float],
                "takeoff_uid": str,
                "condition_uid": str,
                "layer_uid": str,
                "area_uid": str,
                "page_uid": str,
                "layout": int,
            },
            "SceneTowerCraneLayout": {"parts": List[str], "matrices": List[float]},
            "SceneTowerCranes": {
                "model_base64": str,
                "units_per_metre": float,
                "credit": Dict[str, str],
                "layouts": List[module.SceneTowerCraneLayout],
                "placements": List[module.SceneTowerCranePlacement],
                "render_bounds": module.SceneBoundsConfig,
                "parts_without_edges": List[str],
            },
            "SceneGeometryEntry": {
                "vertices": List[float],
                "normals": List[float],
                "indices": List[int],
                "color": List[float],
                "opacity": float,
                "name": str,
                "visible": bool,
                "takeoff_uid": str,
                "page_uid": str,
                "condition_uid": str,
                "area_uid": str,
                "layer_uid": str,
                "cdn_type_uid": str,
                "cdn_type_name": str,
            },
            "SceneLayerEntry": {
                "uid": str,
                "name": str,
                "visible": bool,
                "sequence": int,
            },
            "SceneConditionEntry": {
                "uid": str,
                "name": str,
                "layer_uid": str,
                "visible": bool,
                "cdn_type_uid": str,
                "cdn_type_name": str,
                "color": str,
                "ref_no": int,
            },
            "SceneAreaEntry": {
                "uid": str,
                "name": str,
                "visible": bool,
                "sequence": int,
            },
            "ScenePageImageLayer": {"uid": str, "name": str, "visible": bool},
            "ScenePdfDocumentEntry": {"uid": str, "data_base64": str},
            "ScenePageEntry": {
                "plane_x": float,
                "plane_y": float,
                "plane_z": float,
                "plane_width": float,
                "plane_height": float,
                "plane_flip_u": bool,
                "plane_flip_v": bool,
                "uid": str,
                "label": str,
                "name": str,
                "sheet_no": str,
                "sequence": int,
                "width": float,
                "height": float,
                "page_width": float,
                "page_height": float,
                "image_layer_uid": str,
                "visible": bool,
                "pdf_document_uid": str,
                "pdf_page_index": int,
            },
            "SceneTakeoff2DEntry": {
                "takeoff_uid": str,
                "page_uid": str,
                "condition_uid": str,
                "area_uid": str,
                "layer_uid": str,
                "name": str,
                "visible": bool,
                "kind": str,
                "color": str,
                "opacity": float,
                "rings": List[List[List[float]]],
                "is_negative": bool,
            },
            "SceneElevationCalloutEntry": {
                "page_uid": str,
                "condition_uid": str,
                "area_uid": str,
                "layer_uid": str,
                "x": float,
                "y": float,
                "lines": List[str],
                "color": str,
            },
            "SceneData": {
                "title": str,
                "geometries": List[module.SceneGeometryEntry],
                "camera": module.SceneCameraConfig,
                "bounds": module.SceneBoundsConfig,
                "layers": List[module.SceneLayerEntry],
                "conditions": List[module.SceneConditionEntry],
                "areas": List[module.SceneAreaEntry],
                "page_image_layer": module.ScenePageImageLayer,
                "pages": List[module.ScenePageEntry],
                "active_page_uid": str,
                "selected_page_uids": List[str],
                "pdf_documents": List[module.ScenePdfDocumentEntry],
                "takeoffs_2d": List[module.SceneTakeoff2DEntry],
                "elevation_callouts": List[module.SceneElevationCalloutEntry],
                "display_modes": module.SceneDisplayModesConfig,
                "subtitle": str,
                "view_options": module.SceneViewOptionsConfig,
                "tower_cranes": module.SceneTowerCranes,
            },
        }
        for name, hints in expected.items():
            with self.subTest(typed_dict=name):
                self.assertEqual(get_type_hints(getattr(module, name)), hints)
        self.assertEqual(len(expected), 17)

    def test_required_and_optional_key_sets_are_exact(self):
        from ost_visualizer.application.dtos import scene_data_dto as module

        plane_keys = {
            "plane_x",
            "plane_y",
            "plane_z",
            "plane_width",
            "plane_height",
            "plane_flip_u",
            "plane_flip_v",
        }
        self.assertEqual(
            module.ScenePageEntry.__required_keys__,
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
            },
        )
        self.assertEqual(module.ScenePageEntry.__optional_keys__, plane_keys)
        self.assertEqual(
            SceneData.__optional_keys__,
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
                "subtitle",
                "view_options",
                "tower_cranes",
            },
        )
        for name in (
            "SceneCameraConfig",
            "SceneBoundsConfig",
            "SceneDisplayModesConfig",
            "SceneViewOptionsConfig",
            "SceneTowerCranePlacement",
            "SceneTowerCraneLayout",
            "SceneTowerCranes",
            "SceneGeometryEntry",
            "SceneLayerEntry",
            "SceneConditionEntry",
            "SceneAreaEntry",
            "ScenePageImageLayer",
            "ScenePdfDocumentEntry",
            "SceneTakeoff2DEntry",
            "SceneElevationCalloutEntry",
        ):
            with self.subTest(typed_dict=name):
                typed_dict = getattr(module, name)
                self.assertEqual(typed_dict.__optional_keys__, frozenset())
                self.assertEqual(
                    typed_dict.__required_keys__, set(typed_dict.__annotations__)
                )


if __name__ == "__main__":
    unittest.main()
