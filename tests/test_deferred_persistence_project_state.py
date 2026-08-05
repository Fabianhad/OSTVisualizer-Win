import unittest
from types import SimpleNamespace
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.file_results import BidLoadResult
from ost_visualizer.domain.entities.identity_refs import BidRef
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
        self.bid_layer_visibility = {}
        self.bid_layer_names_by_uid = {}
        self.bid_layer_visibility_by_name = {}
        self.bid_layers = []
        self.annotations = []
        self.bid_takeoffs = []
        self.bid_takeoff_extras = {}
        self.page_area_selections = {}
        self.current_bid_ref = BidRef("test.mdb", "bid-1")

    def get_bid_conditions(self):
        return dict(self.bid_conditions)

    def get_all_pages(self):
        return list(self.pages)

    def get_all_annotations(self):
        return list(self.annotations)

    def add_annotations(self, annotations):
        self.annotations.extend(annotations)

    def set_annotations(self, annotations):
        self.annotations = list(annotations)

    def set_pages(self, pages):
        self.pages = list(pages.values())


class RecordingProjectDataService(ProjectDataService):
    def __init__(self, model):
        super().__init__(model)
        self.annotation_visibility_syncs = 0

    def _synchronize_annotation_visibility(self, layer_uids=None):
        self.annotation_visibility_syncs += 1
        super()._synchronize_annotation_visibility(layer_uids)


class DeferredPersistenceProjectStateTests(unittest.TestCase):
    def test_remote_family_updates_synchronize_annotation_visibility_once(self):
        cases = (
            ("annotations only", {"annotations"}, True, False),
            ("layers only", {"layers"}, False, False),
            ("annotations and layers", {"annotations", "layers"}, True, False),
            ("pages and annotations", {"pages", "annotations"}, True, True),
            ("empty families", set(), False, False),
        )
        for name, families, replace_annotation, replace_pages in cases:
            with self.subTest(name=name):
                model = FakeProjectModel()
                existing = BidAnnotation(
                    uid="ann-existing",
                    annotation_type="text",
                    page_uid="p1",
                    layer_uid="annotation",
                    visible=True,
                )
                incoming = BidAnnotation(
                    uid="ann-incoming",
                    annotation_type="text",
                    page_uid="p-new",
                    layer_uid="annotation",
                    visible=True,
                )
                model.annotations = [existing]
                service = RecordingProjectDataService(model)
                service.set_bid_layer_visibility(
                    [SimpleNamespace(uid="annotation", name="Annotation", show=False)]
                )
                service.annotation_visibility_syncs = 0
                result = BidLoadResult(
                    bid_annotations=[incoming],
                    bid_layers=[
                        SimpleNamespace(uid="annotation", name="Annotation", show=True)
                    ],
                    pages={"p-new": SimpleNamespace(uid="p-new")},
                )
                self.assertTrue(
                    service.replace_remote_bid_families(
                        model.current_bid_ref, result, families
                    )
                )
                expected_annotations = [incoming] if replace_annotation else [existing]
                self.assertEqual(model.annotations, expected_annotations)
                self.assertTrue(
                    all(
                        annotation.visible is ("layers" in families)
                        for annotation in model.annotations
                    )
                )
                self.assertEqual(
                    [page.uid for page in model.pages],
                    ["p-new"] if replace_pages else ["p1", "p2"],
                )
                self.assertEqual(
                    service.annotation_visibility_syncs,
                    1 if families & {"annotations", "layers"} else 0,
                )

    def test_combined_remote_family_replacement_does_not_duplicate_annotations(self):
        model = FakeProjectModel()
        service = ProjectDataService(model)
        annotation = BidAnnotation(
            uid="ann-1",
            annotation_type="rect",
            page_uid="p1",
            layer_uid="annotation",
        )
        result = BidLoadResult(
            bid_annotations=[annotation],
            bid_layers=[
                SimpleNamespace(uid="annotation", name="Annotation", show=True)
            ],
        )
        for _ in range(2):
            self.assertTrue(
                service.replace_remote_bid_families(
                    model.current_bid_ref,
                    result,
                    {"annotations", "layers"},
                )
            )
        self.assertEqual([item.uid for item in model.annotations], ["ann-1"])
        self.assertTrue(model.annotations[0].visible)

    def test_remote_page_load_applies_initial_hidden_annotation_layer_once(self):
        model = FakeProjectModel()
        service = RecordingProjectDataService(model)
        annotation = BidAnnotation(
            uid="ann-hidden",
            annotation_type="dimension",
            page_uid="p-new",
            layer_uid="annotation",
            visible=True,
        )
        result = BidLoadResult(
            bid_annotations=[annotation],
            bid_layers=[
                SimpleNamespace(uid="annotation", name="Annotation", show=False)
            ],
            pages={"p-new": SimpleNamespace(uid="p-new")},
        )
        self.assertTrue(
            service.replace_remote_bid_families(
                model.current_bid_ref,
                result,
                {"annotations", "layers", "pages"},
            )
        )
        self.assertEqual([item.uid for item in model.annotations], ["ann-hidden"])
        self.assertFalse(model.annotations[0].visible)
        self.assertEqual([page.uid for page in model.pages], ["p-new"])
        self.assertEqual(service.annotation_visibility_syncs, 1)

    def test_loaded_layer_visibility_tracks_hidden_layer_uids(self):
        model = FakeProjectModel()
        service = ProjectDataService(model)
        service.set_bid_layer_visibility(
            [
                SimpleNamespace(uid="l1", name="Annotation", show=False),
                SimpleNamespace(uid="l2", name="Takeoff", show=True),
            ]
        )
        self.assertEqual(service.get_hidden_layer_uids(), {"l1"})

    def test_annotation_layer_visibility_tracks_loaded_and_toggled_state(self):
        model = FakeProjectModel()
        annotation = BidAnnotation(
            uid="ann-1",
            annotation_type="text",
            layer_uid="annotation",
            visible=False,
        )
        model.annotations = [annotation]
        service = ProjectDataService(model)
        service.set_bid_layer_visibility(
            [
                SimpleNamespace(uid="annotation", name="Annotation", show=True),
                SimpleNamespace(uid="takeoff", name="Takeoff", show=True),
            ]
        )
        self.assertTrue(service.is_annotation_layer_visible())
        self.assertTrue(annotation.visible)
        service.update_layer_visibility("annotation", False)
        self.assertFalse(service.is_annotation_layer_visible())
        self.assertFalse(annotation.visible)
        service.update_all_layer_visibility(True)
        self.assertTrue(service.is_annotation_layer_visible())
        self.assertTrue(annotation.visible)

    def test_unrelated_layer_toggle_does_not_change_annotation_visibility(self):
        model = FakeProjectModel()
        annotation = BidAnnotation(
            uid="ann-1",
            annotation_type="rect",
            layer_uid="annotation",
            visible=False,
        )
        model.annotations = [annotation]
        service = ProjectDataService(model)
        service.set_bid_layer_visibility(
            [
                SimpleNamespace(uid="annotation", name="Annotation", show=False),
                SimpleNamespace(uid="takeoff", name="Takeoff", show=True),
            ]
        )
        service.update_layer_visibility("takeoff", False)
        self.assertFalse(annotation.visible)

    def test_annotation_added_while_layer_hidden_is_revealed_by_same_state_path(self):
        model = FakeProjectModel()
        service = ProjectDataService(model)
        service.set_bid_layer_visibility(
            [SimpleNamespace(uid="annotation", name="Annotation", show=False)]
        )
        annotations = [
            BidAnnotation(
                uid=f"ann-{annotation_type}",
                annotation_type=annotation_type,
                layer_uid="annotation",
                visible=True,
            )
            for annotation_type in ("text", "dimension", "arrow", "hotlink")
        ]
        service.add_annotations(annotations)
        self.assertTrue(all(not annotation.visible for annotation in annotations))
        service.update_layer_visibility("annotation", True)
        self.assertTrue(all(annotation.visible for annotation in annotations))

    def test_annotation_layer_visibility_prefers_layer_uid_state(self):
        model = FakeProjectModel()
        model.bid_layer_visibility = {"l1": False}
        model.bid_layer_names_by_uid = {"l1": "Annotation"}
        model.bid_layer_visibility_by_name = {"annotation": True}
        service = ProjectDataService(model)
        self.assertEqual(service.get_annotation_layer_uid(), "l1")
        self.assertFalse(service.is_annotation_layer_visible())

    def test_layer_visibility_updates_condition_memory_immediately(self):
        model = FakeProjectModel()
        service = ProjectDataService(model)
        changed_pages = service.update_layer_visibility("l1", False)
        self.assertEqual(changed_pages, [])
        self.assertFalse(model.bid_conditions["c1"].layer_visible)
        self.assertTrue(model.bid_conditions["c2"].layer_visible)
        self.assertTrue(model.pages[0].layer_visible)
        self.assertEqual(service.get_hidden_layer_uids(), {"l1"})

    def test_image_layer_visibility_updates_page_memory_immediately(self):
        model = FakeProjectModel()
        service = ProjectDataService(model)
        service.set_bid_layer_visibility(
            [
                SimpleNamespace(uid="image", name="Image", show=True),
                SimpleNamespace(uid="l1", name="Takeoff", show=True),
            ]
        )
        changed_pages = service.update_layer_visibility("image", False)
        self.assertEqual(changed_pages, ["p1", "p2"])
        self.assertFalse(model.pages[0].layer_visible)
        self.assertFalse(model.pages[1].layer_visible)
        self.assertEqual(service.get_hidden_layer_uids(), {"image"})

    def test_layer_visibility_state_sources_remain_synchronized_by_layer_kind(self):
        model = FakeProjectModel()
        service = ProjectDataService(model)
        service.set_bid_layer_visibility(
            [
                SimpleNamespace(uid="image", name="Image", show=True),
                SimpleNamespace(uid="annotation", name="Annotation", show=True),
                SimpleNamespace(uid="l1", name="Takeoff", show=True),
                SimpleNamespace(uid="custom", name="Future Visual", show=True),
            ]
        )
        with self.subTest(layer="annotation"):
            changed_pages = service.update_layer_visibility("annotation", False)
            self.assertEqual(changed_pages, [])
            self.assertFalse(model.bid_layer_visibility["annotation"])
            self.assertFalse(model.bid_layer_visibility_by_name["annotation"])
            self.assertTrue(model.bid_conditions["c1"].layer_visible)
            self.assertTrue(model.pages[0].layer_visible)
        with self.subTest(layer="condition"):
            changed_pages = service.update_layer_visibility("l1", False)
            self.assertEqual(changed_pages, [])
            self.assertFalse(model.bid_layer_visibility["l1"])
            self.assertFalse(model.bid_layer_visibility_by_name["takeoff"])
            self.assertFalse(model.bid_conditions["c1"].layer_visible)
            self.assertTrue(model.bid_conditions["c2"].layer_visible)
            self.assertTrue(model.pages[0].layer_visible)
        with self.subTest(layer="custom"):
            changed_pages = service.update_layer_visibility("custom", False)
            self.assertEqual(changed_pages, [])
            self.assertFalse(model.bid_layer_visibility["custom"])
            self.assertFalse(model.bid_layer_visibility_by_name["future visual"])
            self.assertTrue(model.pages[0].layer_visible)
        with self.subTest(layer="image"):
            changed_pages = service.update_layer_visibility("image", False)
            self.assertEqual(changed_pages, ["p1", "p2"])
            self.assertFalse(model.bid_layer_visibility["image"])
            self.assertFalse(model.bid_layer_visibility_by_name["image"])
            self.assertFalse(model.pages[0].layer_visible)
            self.assertFalse(model.pages[1].layer_visible)

    def test_non_image_layer_visibility_does_not_update_page_memory_by_name_guess(
        self,
    ):
        model = FakeProjectModel()
        service = ProjectDataService(model)
        service.set_bid_layer_visibility(
            [
                SimpleNamespace(uid="l1", name="Future Visual", show=True),
                SimpleNamespace(uid="image", name="Image", show=True),
            ]
        )
        changed_pages = service.update_layer_visibility("l1", False)
        self.assertEqual(changed_pages, [])
        self.assertTrue(model.pages[0].layer_visible)
        self.assertTrue(model.pages[1].layer_visible)
        self.assertFalse(model.bid_conditions["c1"].layer_visible)

    def test_show_all_layer_visibility_updates_conditions_and_pages_immediately(self):
        model = FakeProjectModel()
        model.bid_conditions["c1"].layer_visible = False
        model.pages[0].layer_visible = False
        model.bid_layer_visibility = {"l1": False, "l2": True}
        model.bid_layer_names_by_uid = {"l1": "annotation", "l2": "takeoff"}
        model.bid_layer_visibility_by_name = {"annotation": False, "takeoff": True}
        service = ProjectDataService(model)
        changed_pages = service.update_all_layer_visibility(True)
        self.assertEqual(changed_pages, ["p1", "p2"])
        self.assertTrue(model.bid_conditions["c1"].layer_visible)
        self.assertTrue(model.bid_conditions["c2"].layer_visible)
        self.assertTrue(model.pages[0].layer_visible)
        self.assertTrue(model.pages[1].layer_visible)
        self.assertEqual(service.get_hidden_layer_uids(), set())

    def test_remove_takeoffs_clears_page_bid_and_supplemental_state(self):
        model = FakeProjectModel()
        removed = SimpleNamespace(uid="t1", page_uid="p1")
        retained = SimpleNamespace(uid="t2", page_uid="p2")
        model.pages[0].takeoffs = [removed]
        model.pages[1].takeoffs = [retained]
        model.bid_takeoffs = [removed, retained]
        model.bid_takeoff_extras = {
            "t1": {"condition_name": "Removed"},
            "t2": {"condition_name": "Retained"},
        }
        model.get_all_takeoffs = lambda: [
            takeoff for page in model.pages for takeoff in page.takeoffs
        ]
        model.get_page = lambda uid: next(
            (page for page in model.pages if page.uid == uid), None
        )
        changed_pages = ProjectDataService(model).remove_takeoffs(["t1"])
        self.assertEqual(changed_pages, ["p1"])
        self.assertEqual(model.bid_takeoffs, [retained])
        self.assertEqual(model.pages[0].takeoffs, [])
        self.assertEqual(model.pages[1].takeoffs, [retained])
        self.assertEqual(
            model.bid_takeoff_extras,
            {"t2": {"condition_name": "Retained"}},
        )


if __name__ == "__main__":
    unittest.main()
