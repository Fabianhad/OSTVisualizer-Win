import unittest
from ost_visualizer.application.services.project_read_service import ProjectReadService
from ost_visualizer.domain.entities.layer import BidLayer


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


class FakeLayerReader:
    def __init__(self):
        self.layers = [
            _layer("image", "Image", 0),
            _layer("annotation", "Annotation", 1),
            _layer("default", "Default", 2),
            _layer("comments", "Comments", 3),
            _layer("custom", "Custom", 4, is_template=False),
        ]

    def get_bid_layers_for_sidebar(self, _file_path, _bid_uid):
        return list(self.layers)

    def get_default_layers(self, _file_path):
        return [layer for layer in self.layers if layer.is_template]


class ProjectReadServiceLayerTests(unittest.TestCase):
    def test_merged_bid_layers_hide_comments_layer_from_project_ui(self):
        service = ProjectReadService(FakeLayerReader())
        layers = service.get_merged_bid_layers("a.mdb", "bid-1")
        self.assertEqual(
            [layer.name for layer in layers],
            ["Image", "Annotation", "Default", "Custom"],
        )

    def test_default_layers_keep_comments_layer(self):
        service = ProjectReadService(FakeLayerReader())
        layers = service.get_default_layers("a.mdb")
        self.assertEqual(
            [layer.name for layer in layers],
            ["Image", "Annotation", "Default", "Comments"],
        )


if __name__ == "__main__":
    unittest.main()
