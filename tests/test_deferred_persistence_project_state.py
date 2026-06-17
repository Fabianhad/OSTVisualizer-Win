import unittest
from types import SimpleNamespace

from ost_visualizer.domain.services.project_data_service import ProjectDataService


class FakeProjectModel:
    def __init__(self):
        self.bid_conditions = {
            "c1": SimpleNamespace(uid="c1", layer_uid="l1", layer_visible=True),
            "c2": SimpleNamespace(uid="c2", layer_uid="l2", layer_visible=True),
        }
        self.pages = [
            SimpleNamespace(uid="p1", layer_visible=True),
            SimpleNamespace(uid="p2", layer_visible=True),
        ]

    def get_bid_conditions(self):
        return dict(self.bid_conditions)

    def get_all_pages(self):
        return list(self.pages)


class DeferredPersistenceProjectStateTests(unittest.TestCase):
    def test_layer_visibility_updates_condition_memory_immediately(self):
        model = FakeProjectModel()
        service = ProjectDataService(model)

        changed_pages = service.update_layer_visibility("l1", False)

        self.assertEqual(changed_pages, [])
        self.assertFalse(model.bid_conditions["c1"].layer_visible)
        self.assertTrue(model.bid_conditions["c2"].layer_visible)
        self.assertTrue(model.pages[0].layer_visible)

    def test_image_layer_visibility_updates_page_memory_immediately(self):
        model = FakeProjectModel()
        service = ProjectDataService(model)

        changed_pages = service.update_layer_visibility("image", False, image_layer=True)

        self.assertEqual(changed_pages, ["p1", "p2"])
        self.assertFalse(model.pages[0].layer_visible)
        self.assertFalse(model.pages[1].layer_visible)

    def test_show_all_layer_visibility_updates_conditions_and_pages_immediately(self):
        model = FakeProjectModel()
        model.bid_conditions["c1"].layer_visible = False
        model.pages[0].layer_visible = False
        service = ProjectDataService(model)

        changed_pages = service.update_all_layer_visibility(True)

        self.assertEqual(changed_pages, ["p1", "p2"])
        self.assertTrue(model.bid_conditions["c1"].layer_visible)
        self.assertTrue(model.bid_conditions["c2"].layer_visible)
        self.assertTrue(model.pages[0].layer_visible)
        self.assertTrue(model.pages[1].layer_visible)


if __name__ == "__main__":
    unittest.main()
