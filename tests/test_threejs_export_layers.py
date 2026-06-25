import unittest
from types import SimpleNamespace

from ost_visualizer.application.services.export_service import ExportService
from ost_visualizer.application.dtos.export_dto import ExportRequestDto
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.layer import BidLayer
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from ost_visualizer.presentation.visualization.core.mesh_generator import MeshData
from ost_visualizer.presentation.visualization.renderers.threejs.adapters.threejs_mesh_adapter import (
    ThreejsMeshAdapter,
)
from ost_visualizer.presentation.visualization.services.color_service import ColorService


class _ProjectModel:
    def __init__(self):
        self.bid_conditions = {
            "visible": Condition(
                uid="visible",
                layer_uid="layer-visible",
                layer_visible=True,
            ),
            "hidden": Condition(
                uid="hidden",
                layer_uid="layer-hidden",
                layer_visible=False,
            ),
        }
        self.takeoffs = {
            "page-1": [
                Takeoff(uid="takeoff-visible", condition_uid="visible", page_uid="page-1"),
                Takeoff(uid="takeoff-hidden", condition_uid="hidden", page_uid="page-1"),
            ]
        }

    def get_page_takeoffs(self, page_uid):
        return list(self.takeoffs.get(page_uid, []))


class _ExportStrategy:
    name = "HTML"

    def __init__(self, extension):
        self.extension = extension
        self.calls = []

    def get_dialog_title(self, page_count):
        return f"Export {page_count}"

    def prepare_filename(self, bid_name, page_names):
        return "export.html"

    def prepare_title(self, bid_name, page_names):
        return "Export"

    def get_kwargs(self, _config_model, _page_area_selections=None):
        return {}

    def execute_export(self, bid_conditions, takeoffs, output_path, **kwargs):
        self.calls.append((bid_conditions, takeoffs, output_path, kwargs))
        return True


class _Provider:
    def __init__(self, strategy):
        self.strategy = strategy

    def get_available_formats(self):
        return [self.strategy.extension]

    def get_export_strategy(self, _format_key):
        return self.strategy


class _ProjectData:
    def __init__(self):
        self.visible_only_calls = []
        self.conditions = {
            "visible": Condition(uid="visible"),
            "hidden": Condition(uid="hidden"),
        }
        self.page = SimpleNamespace(
            uid="page-1",
            scale_factor1=1.0,
            scale_factor2=1.0,
            width_pts=72.0,
            height_pts=144.0,
            image_path="",
            page_index=1,
            layer_visible=False,
        )

    def collect_takeoffs_for_pages(self, page_uids, visible_only=True):
        self.visible_only_calls.append(visible_only)
        return SimpleNamespace(
            takeoffs=[
                Takeoff(uid="takeoff-visible", condition_uid="visible"),
                Takeoff(uid="takeoff-hidden", condition_uid="hidden"),
            ],
            valid_page_uids=list(page_uids),
            page_count=len(page_uids),
            is_empty=lambda: False,
        )

    def get_page_name(self, page_uid):
        return page_uid

    def get_current_bid(self):
        return SimpleNamespace(name="Bid")

    def get_page_area_selections(self):
        return {}

    def get_bid_layer_snapshot(self):
        return [
            BidLayer(
                uid="layer-hidden",
                bid_uid="bid",
                name="Hidden",
                show=False,
                sequence=1,
            )
        ]

    def get_page(self, _page_uid):
        return self.page

    def get_image_layer_uid(self):
        return "image"

    def get_bid_conditions(self):
        return self.conditions


class ThreejsExportLayerTests(unittest.TestCase):
    def test_collect_takeoffs_for_pages_can_include_hidden_layer_takeoffs(self):
        service = ProjectDataService(_ProjectModel())

        visible = service.collect_takeoffs_for_pages(["page-1"])
        all_takeoffs = service.collect_takeoffs_for_pages(
            ["page-1"], visible_only=False
        )

        self.assertEqual([takeoff.uid for takeoff in visible.takeoffs], ["takeoff-visible"])
        self.assertEqual(
            [takeoff.uid for takeoff in all_takeoffs.takeoffs],
            ["takeoff-visible", "takeoff-hidden"],
        )

    def test_bid_layer_snapshot_fallback_filters_comments_layer(self):
        model = SimpleNamespace(
            bid_layers=[],
            bid_layer_names_by_uid={
                "image-layer": "image",
                "comments-layer": "comments",
            },
            bid_layer_visibility={
                "image-layer": True,
                "comments-layer": True,
            },
            current_bid_ref=SimpleNamespace(bid_uid="bid"),
        )
        service = ProjectDataService(model)

        snapshot = service.get_bid_layer_snapshot()

        self.assertEqual([layer.uid for layer in snapshot], ["image-layer"])

    def test_html_export_collects_hidden_takeoffs_and_passes_layer_metadata(self):
        strategy = _ExportStrategy("html")
        project_data = _ProjectData()
        service = ExportService(_Provider(strategy), project_data)

        result = service.export(
            SimpleNamespace(),
            ExportRequestDto(["page-1"], "html", "out.html"),
        )

        self.assertTrue(result.success)
        self.assertEqual(project_data.visible_only_calls, [False])
        self.assertEqual(len(strategy.calls), 1)
        _conditions, takeoffs, _output_path, kwargs = strategy.calls[0]
        self.assertEqual([takeoff.uid for takeoff in takeoffs], ["takeoff-visible", "takeoff-hidden"])
        self.assertEqual(kwargs["layers"][0].uid, "layer-hidden")
        self.assertEqual(kwargs["page_image_layer"]["uid"], "image")
        self.assertFalse(kwargs["page_image_layer"]["visible"])

    def test_non_html_export_keeps_visible_only_collection(self):
        strategy = _ExportStrategy("obj")
        strategy.name = "OBJ"
        project_data = _ProjectData()
        service = ExportService(_Provider(strategy), project_data)

        result = service.export(
            SimpleNamespace(),
            ExportRequestDto(["page-1"], "obj", "out.obj"),
        )

        self.assertTrue(result.success)
        self.assertEqual(project_data.visible_only_calls, [True])

    def test_threejs_adapter_exports_layer_and_condition_metadata(self):
        adapter = ThreejsMeshAdapter(ColorService())
        mesh = MeshData(
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            faces=[(0, 1, 2)],
        )

        scene = adapter.build_scene_data(
            [
                (
                    mesh,
                    {
                        "color": "#ff0000",
                        "opacity": 1.0,
                        "name": "Condition",
                        "takeoff_uid": "takeoff-1",
                        "condition_uid": "condition-1",
                        "layer_uid": "layer-1",
                        "layer_visible": False,
                        "visible": True,
                        "cdn_type_uid": "type-1",
                        "cdn_type_name": "Concrete",
                    },
                )
            ],
            (0.0, 1.0, 0.0, 1.0, 0.0, 1.0),
            "Layer Scene",
            layers=[
                BidLayer(
                    uid="layer-1",
                    bid_uid="bid",
                    name="Takeoff",
                    show=False,
                    sequence=7,
                )
            ],
            page_image_layer={"uid": "image", "name": "Image", "visible": True},
        )

        geometry = scene["geometries"][0]
        self.assertEqual(geometry["takeoff_uid"], "takeoff-1")
        self.assertEqual(geometry["condition_uid"], "condition-1")
        self.assertEqual(geometry["layer_uid"], "layer-1")
        self.assertTrue(geometry["visible"])
        self.assertEqual(scene["conditions"][0]["layer_uid"], "layer-1")
        self.assertFalse(scene["conditions"][0]["visible"])
        self.assertEqual(scene["layers"][0]["uid"], "layer-1")
        self.assertFalse(scene["layers"][0]["visible"])
        self.assertEqual(scene["page_image_layer"]["uid"], "image")


if __name__ == "__main__":
    unittest.main()
