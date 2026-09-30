import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.use_cases.annotation_view.open_annotation_view_use_case import (
    OpenAnnotationViewUseCase,
)
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_NAMED_VIEW,
    BidAnnotation,
)
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.identity_refs import BidRef


class OpenAnnotationViewUseCaseHotlinkTests(unittest.TestCase):
    def test_hotlink_open_targets_resolved_named_view_page(self):
        bid_ref = BidRef(file_path="job.ost", bid_uid="bid-1")
        named_view = BidAnnotation(
            uid="view-1",
            annotation_type="namedview",
            page_uid="page-2",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 5.0, 0.0, 5.0],
        )
        project_data = SimpleNamespace(
            get_current_bid_ref=lambda: bid_ref,
            get_all_annotations=lambda: [named_view],
        )
        calls = []
        view_manager = SimpleNamespace(
            is_view_open=lambda: False,
            open_view=lambda **view_options: calls.append(view_options) or "view-id",
        )
        use_case = OpenAnnotationViewUseCase(view_manager, project_data)
        result = use_case.execute_from_hotlink(
            AppEvents.HOTLINK_CLICKED(
                hotlink_uid="hotlink-1",
                bid_page_uid="page-1",
                target_view_uid="view-1",
                position_x=1.0,
                position_y=2.0,
            )
        )
        self.assertEqual(result, "view-id")
        self.assertEqual(calls[0]["bid_ref"], bid_ref)
        self.assertEqual(calls[0]["target_page_uid"], "page-2")
        self.assertEqual(calls[0]["target_named_view_uid"], "view-1")

    def test_hotlink_preference_can_route_to_view_window_manager(self):
        bid_ref = BidRef(file_path="job.ost", bid_uid="bid-1")
        named_view = BidAnnotation(
            uid="view-1",
            annotation_type="namedview",
            page_uid="page-2",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 5.0, 0.0, 5.0],
        )
        project_data = SimpleNamespace(
            get_current_bid_ref=lambda: bid_ref,
            get_all_annotations=lambda: [named_view],
        )
        annotation_calls = []
        view_calls = []
        annotation_manager = SimpleNamespace(
            is_view_open=lambda: False,
            open_view=lambda **view_options: annotation_calls.append(view_options)
            or "annotation",
        )
        view_manager = SimpleNamespace(
            is_view_open=lambda: False,
            open_view=lambda **view_options: view_calls.append(view_options) or "view",
        )
        use_case = OpenAnnotationViewUseCase(
            annotation_manager,
            project_data,
            config_model=Config(hotlink_target="view"),
            view_window_manager=view_manager,
        )
        result = use_case.execute_from_hotlink(
            AppEvents.HOTLINK_CLICKED(
                hotlink_uid="hotlink-1",
                bid_page_uid="page-1",
                target_view_uid="view-1",
            )
        )
        self.assertEqual(result, "view")
        self.assertEqual(annotation_calls, [])
        self.assertEqual(view_calls[0]["target_page_uid"], "page-2")

    def test_hotlink_preference_can_route_to_main_window_manager(self):
        bid_ref = BidRef(file_path="job.ost", bid_uid="bid-1")
        named_view = BidAnnotation(
            uid="view-1",
            annotation_type="namedview",
            page_uid="page-2",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 5.0, 0.0, 5.0],
        )
        project_data = SimpleNamespace(
            get_current_bid_ref=lambda: bid_ref,
            get_all_annotations=lambda: [named_view],
        )
        annotation_calls = []
        view_calls = []
        main_calls = []
        annotation_manager = SimpleNamespace(
            is_view_open=lambda: False,
            open_view=lambda **view_options: annotation_calls.append(view_options)
            or "annotation",
        )
        view_manager = SimpleNamespace(
            is_view_open=lambda: False,
            open_view=lambda **view_options: view_calls.append(view_options) or "view",
        )
        main_manager = SimpleNamespace(
            is_view_open=lambda: True,
            bring_to_front=lambda: main_calls.append(("front",)),
            navigate_to_view=lambda page_uid, named_view_uid: main_calls.append(
                (page_uid, named_view_uid)
            ),
        )
        use_case = OpenAnnotationViewUseCase(
            annotation_manager,
            project_data,
            config_model=Config(hotlink_target="main"),
            view_window_manager=view_manager,
            main_view_manager=main_manager,
        )
        result = use_case.execute_from_hotlink(
            AppEvents.HOTLINK_CLICKED(
                hotlink_uid="hotlink-1",
                bid_page_uid="page-1",
                target_view_uid="view-1",
            )
        )
        self.assertEqual(result, "__current__")
        self.assertEqual(annotation_calls, [])
        self.assertEqual(view_calls, [])
        self.assertEqual(main_calls, [("front",), ("page-2", "view-1")])
