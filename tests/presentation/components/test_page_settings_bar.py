import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.components.page_settings_bar import PageSettingsBar
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete
from tests.helpers.workspace_state import make_workspace_state_model
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.components.page_settings_bar import (
    PageSettingsBar as MasterPageSettingsBar,
)
from tests.helpers.workspace_state import (
    make_workspace_state_model,
    with_workspace_state,
)
from tests.presentation.dialogs.master_data_support import (
    FakeIconProvider as _master_data_support_FakeIconProvider,
    MasterPageSettingsBar as _master_data_support_MasterPageSettingsBar,
    _app as _master_data_support__app,
)
from ost_visualizer.application.events.app_events import AppEvents
from unittest.mock import patch


class PageAreaContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_area_return_requires_current_editable_page(self):
        for transition in (
            "current",
            "navigate",
            "clear",
            "access",
            "disabled",
            "replacement",
            "unprojected_replacement",
            "close",
            "same_page_projection",
            "area_projection_replaced",
            "selected_area_missing",
        ):
            for accepted in (False, True):
                with self.subTest(transition=transition, accepted=accepted):
                    access = Mock()
                    access.is_allowed.return_value = True
                    areas = [
                        BidArea("a", "bid", "", "A", 0),
                        BidArea("b", "bid", "", "B", 1),
                    ]
                    pages = {"page": SimpleNamespace(uid="page")}
                    load = Mock(side_effect=lambda *_args: list(areas))
                    bar = PageSettingsBar(
                        Mock(),
                        Mock(),
                        Mock(),
                        access,
                        make_workspace_state_model(),
                        get_page_fn=pages.get,
                        load_areas_fn=load,
                        save_areas_fn=lambda *args, **kwargs: {},
                    )
                    bar.load_bid_areas(BidRef("db", "bid"))
                    bar.load_page("page", 1, 1, "a")
                    bar.set_interactive(True)
                    changes = Mock()
                    bar.area_change_requested.connect(changes)

                    def execute(child, bus):
                        if transition == "close":
                            bar.close()
                        elif transition == "unprojected_replacement":
                            pages["page"] = SimpleNamespace(uid="page")
                        elif transition == "same_page_projection":
                            bar.load_page("page", 1, 1, "a")
                        elif transition == "area_projection_replaced":
                            bar.load_bid_areas(BidRef("db", "bid"), areas=areas)
                        elif transition == "replacement":
                            pages["page"] = SimpleNamespace(uid="page")
                            bar.load_page("page", 2, 3, "b")
                        elif transition == "navigate":
                            bar.load_page("other", 1, 1, "b")
                        elif transition == "clear":
                            bar.clear_page()
                        elif transition == "access":
                            access.is_allowed.return_value = False
                        elif transition == "disabled":
                            bar.set_interactive(False)
                        if transition != "clear":
                            bar.area_combo.set_current_area_uid("b")
                        if accepted:
                            child._selected_uid = (
                                "missing"
                                if transition == "selected_area_missing"
                                else "a"
                            )
                        load.reset_mock()
                        return (
                            QtWidgets.QDialog.DialogCode.Accepted
                            if accepted
                            else QtWidgets.QDialog.DialogCode.Rejected
                        )

                    try:
                        with patch(
                            "ost_visualizer.presentation.components.page_settings_bar.exec_with_ost_blocking",
                            execute,
                        ):
                            bar._on_area_browse()
                        self.assertEqual(
                            load.call_count,
                            (
                                1
                                if transition
                                in (
                                    "current",
                                    "same_page_projection",
                                    "selected_area_missing",
                                )
                                else 0
                            ),
                        )
                        if transition not in (
                            "current",
                            "same_page_projection",
                            "clear",
                        ):
                            self.assertEqual(bar.get_current_area_uid(), "b")
                        if transition not in ("current", "same_page_projection"):
                            changes.assert_not_called()
                        elif accepted:
                            self.assertEqual(bar.get_current_area_uid(), "a")
                            self.assertEqual(
                                changes.call_args_list, [call("db", "page", "a")]
                            )
                        else:
                            self.assertEqual(bar.get_current_area_uid(), "b")
                            changes.assert_not_called()
                    finally:
                        delete(bar)
                        QtCore.QCoreApplication.sendPostedEvents(
                            None, QtCore.QEvent.Type.DeferredDelete
                        )


class PageSettingsScaleDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _master_data_support__app()

    def setUp(self):
        self.bar = _master_data_support_MasterPageSettingsBar(
            _master_data_support_FakeIconProvider(),
            event_bus=EventBus(),
            refresh_areas_fn=lambda _file_path: None,
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            get_page_fn=lambda uid, pages={}: pages.setdefault(uid, object()),
        )

    def tearDown(self):
        self.bar.deleteLater()
        self.app.processEvents()

    def test_custom_scale_display_tracks_page_refresh_without_emitting_requests(self):
        scale_requests = []
        custom_requests = []
        self.bar.scale_change_requested.connect(
            lambda *args: scale_requests.append(args)
        )
        self.bar.custom_scale_requested.connect(
            lambda *args: custom_requests.append(args)
        )
        index_changes = []
        self.bar.scale_combo.currentIndexChanged.connect(index_changes.append)
        initial_count = self.bar.scale_combo.count()
        for _ in range(12):
            self.bar.load_page("custom-1", 0.26, 12.0, "")
        self.assertEqual(self.bar.scale_combo.currentText(), '0.26" = 1\' 0"')
        self.assertEqual(self.bar.scale_combo.count(), initial_count)
        self.assertEqual(scale_requests, [])
        self.assertEqual(custom_requests, [])
        self.assertEqual(index_changes, [])
        self.bar.load_page("custom-2", 0.3751, 12.0, "")
        self.assertEqual(self.bar.scale_combo.currentText(), '0.3751" = 1\' 0"')
        self.assertEqual(self.bar.scale_combo.count(), initial_count)
        self.bar.load_page("custom-1", 0.26000000000000001, 12.0, "")
        self.assertEqual(self.bar.scale_combo.currentText(), '0.26" = 1\' 0"')
        self.assertEqual(self.bar.scale_combo.count(), initial_count)

    def test_switching_between_custom_and_predefined_resets_one_custom_item(self):
        custom_index = self.bar.scale_combo.count() - 1
        initial_count = self.bar.scale_combo.count()
        self.bar.load_page("custom", 0.26, 12.0, "")
        self.assertEqual(self.bar.scale_combo.currentIndex(), custom_index)
        self.assertEqual(self.bar.scale_combo.itemText(custom_index), '0.26" = 1\' 0"')
        self.bar.load_page("predefined", 0.125, 12.0, "")
        self.assertEqual(self.bar.scale_combo.currentText(), '1/8" = 1\' 0"')
        self.assertEqual(self.bar.scale_combo.itemText(custom_index), "Custom scale")
        self.bar.load_page("custom", 0.26, 12.0, "")
        self.assertEqual(self.bar.scale_combo.currentIndex(), custom_index)
        self.assertEqual(self.bar.scale_combo.count(), initial_count)

    def test_predefined_and_reloaded_scale_labels_remain_readable(self):
        for sf1, sf2, expected in (
            (1.0, 240.0, '1" = 20\' 0"'),
            (0.125, 12.0, '1/8" = 1\' 0"'),
            (0.1875, 12.0, '3/16" = 1\' 0"'),
        ):
            self.bar.load_page("page", sf1, sf2, "")
            self.assertEqual(self.bar.scale_combo.currentText(), expected)
        self.bar.load_page("custom", 0.26, 12.0, "")
        self.bar.scale_combo.blockSignals(True)
        self.bar.clear_bid()
        self.assertTrue(self.bar.scale_combo.signalsBlocked())
        self.assertEqual(
            self.bar.scale_combo.itemText(self.bar.scale_combo.count() - 1),
            "Custom scale",
        )
        self.assertEqual(self.bar.scale_combo.currentIndex(), -1)
        self.bar.scale_combo.blockSignals(False)
        self.bar.load_page("custom", 0.26, 12.0, "")
        self.assertEqual(self.bar.scale_combo.currentText(), '0.26" = 1\' 0"')

    def test_programmatic_area_updates_preserve_existing_qt_signal_block(self):
        self.bar.area_combo.blockSignals(True)
        try:
            self.bar.load_bid_areas(
                BidRef("db.mdb", "bid-1"),
                areas=[BidArea("area-1", "bid-1", "", "Area 1", 0)],
            )
            self.assertTrue(self.bar.area_combo.signalsBlocked())
            self.bar.load_page("page-1", 1.0, 1.0, "area-1")
            self.assertTrue(self.bar.area_combo.signalsBlocked())
            self.bar.clear_bid()
            self.assertTrue(self.bar.area_combo.signalsBlocked())
        finally:
            self.bar.area_combo.blockSignals(False)
        self.bar.load_bid_areas(
            BidRef("db.mdb", "bid-1"),
            areas=[BidArea("area-1", "bid-1", "", "Area 1", 0)],
        )
        self.bar.load_page("page-1", 1.0, 1.0, "area-1")
        self.bar.clear_bid()
        self.assertFalse(self.bar.area_combo.signalsBlocked())
        self.assertFalse(self.bar.scale_combo.signalsBlocked())

    def test_area_usage_is_owned_and_cleared_with_bid_state(self):
        bid_usage = {"area-1"}
        page_usage = {"area-1"}
        self.bar.load_bid_areas(
            BidRef("db.mdb", "bid-1"),
            areas=[BidArea("area-1", "bid-1", "", "Area 1", 0)],
            areas_with_takeoff=bid_usage,
        )
        self.bar.load_page(
            "page-1",
            1.0,
            1.0,
            "area-1",
            areas_with_takeoff=page_usage,
        )
        bid_usage.clear()
        page_usage.clear()
        self.assertEqual(self.bar._bid_areas_in_use, {"area-1"})
        self.assertEqual(self.bar._page_areas_in_use, {"area-1"})
        self.bar.clear_bid()
        self.assertIsNone(self.bar._bid_areas_in_use)
        self.assertIsNone(self.bar._page_areas_in_use)
        self.assertEqual(self.bar._current_scale_index, -1)

    def test_clear_page_removes_stale_controls_but_retains_loaded_bid(self):
        bid_ref = BidRef("db.mdb", "bid-1")
        self.bar.load_bid_areas(
            bid_ref,
            areas=[BidArea("area-1", "bid-1", "", "Area 1", 0)],
        )
        self.bar.load_page("page-1", 1.0, 1.0, "area-1")
        self.bar.set_interactive(True)
        self.bar.clear_page()
        self.assertEqual(self.bar._bid_ref, bid_ref)
        self.assertIn("area-1", self.bar.area_combo._area_items)
        self.assertIsNone(self.bar._page_uid)
        self.assertEqual(self.bar.scale_combo.currentIndex(), -1)
        self.assertEqual(self.bar.area_combo.get_current_area_uid(), "")
        self.assertFalse(self.bar.scale_combo.isEnabled())
        self.assertFalse(self.bar.area_combo.isEnabled())
        self.assertFalse(self.bar.area_browse_btn.isEnabled())

    def test_non_architectural_custom_and_invalid_scales_use_safe_display(self):
        self.bar.load_page("metric-custom", 2.5, 1000.0, "")
        self.assertEqual(self.bar.scale_combo.currentText(), "2.5 : 1000")
        for sf1, sf2 in (
            (None, 12.0),
            (0.0, 12.0),
            (0.26, 0.0),
            (-0.26, 12.0),
            (0.26, -12.0),
            (float("nan"), 12.0),
            (0.26, float("inf")),
            ("not-a-number", 12.0),
        ):
            with self.subTest(sf1=sf1, sf2=sf2):
                self.bar.load_page("invalid", sf1, sf2, "")
                self.assertEqual(self.bar.scale_combo.currentIndex(), -1)
                self.assertEqual(self.bar.scale_combo.currentText(), "")
                self.assertEqual(self.bar._current_scale_index, -1)
                self.assertEqual(
                    self.bar.scale_combo.itemText(self.bar.scale_combo.count() - 1),
                    "Custom scale",
                )


class MasterDataDialogButtonModeTests(unittest.TestCase):
    def test_page_settings_scale_activation_emits_one_request_per_commit(self):
        bar = _master_data_support_MasterPageSettingsBar(
            _master_data_support_FakeIconProvider(),
            event_bus=EventBus(),
            refresh_areas_fn=lambda _file_path: None,
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            get_page_fn=lambda uid, pages={}: pages.setdefault(uid, object()),
        )
        bar.load_bid_areas(BidRef("db.mdb", "bid-1"), areas=[])
        bar.load_page("page-1", 1.0, 1.0, "")
        bar.set_interactive(True)
        scale_requests = []
        custom_requests = []
        bar.scale_change_requested.connect(
            lambda *args: scale_requests.append(tuple(args))
        )
        bar.custom_scale_requested.connect(
            lambda *args: custom_requests.append(tuple(args))
        )
        try:
            predefined_index = next(
                index
                for index in range(bar.scale_combo.count())
                if isinstance(bar.scale_combo.itemData(index), tuple)
                and bar.scale_combo.itemData(index) != (1.0, 1.0)
            )
            expected_scale = bar.scale_combo.itemData(predefined_index)
            bar.scale_combo.activated.emit(predefined_index)
            bar.scale_combo.activated.emit(predefined_index)
            custom_index = bar.scale_combo.count() - 1
            bar.scale_combo.activated.emit(custom_index)
            self.assertEqual(
                scale_requests,
                [
                    ("db.mdb", "page-1", *expected_scale),
                    ("db.mdb", "page-1", *expected_scale),
                ],
            )
            self.assertEqual(custom_requests, [("db.mdb", "page-1")])
        finally:
            bar.deleteLater()

    def test_page_settings_custom_scale_activation_restores_previous_scale(self):
        bar = _master_data_support_MasterPageSettingsBar(
            _master_data_support_FakeIconProvider(),
            event_bus=EventBus(),
            refresh_areas_fn=lambda _file_path: None,
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            get_page_fn=lambda uid, pages={}: pages.setdefault(uid, object()),
        )
        bar.load_bid_areas(BidRef("db.mdb", "bid-1"), areas=[])
        bar.load_page("page-1", 0.125, 12.0, "")
        bar.set_interactive(True)
        scale_requests = []
        custom_requests = []
        bar.scale_change_requested.connect(
            lambda *args: scale_requests.append(tuple(args))
        )
        bar.custom_scale_requested.connect(
            lambda *args: custom_requests.append(tuple(args))
        )
        try:
            custom_index = bar.scale_combo.count() - 1
            previous_index = bar.scale_combo.currentIndex()
            self.assertEqual(bar.scale_combo.currentText(), '1/8" = 1\' 0"')
            bar.scale_combo.setCurrentIndex(custom_index)
            bar.scale_combo.activated.emit(custom_index)
            self.assertEqual(bar.scale_combo.currentIndex(), previous_index)
            self.assertEqual(custom_requests, [("db.mdb", "page-1")])
            self.assertEqual(scale_requests, [])
        finally:
            bar.deleteLater()

    def test_page_settings_scale_and_area_activation_are_ignored_when_not_editable(
        self,
    ):
        for blocker in ("access", "not_interactive", "no_page", "no_bid"):
            with self.subTest(blocker=blocker):
                allowed = {"value": blocker != "access"}
                bar = _master_data_support_MasterPageSettingsBar(
                    _master_data_support_FakeIconProvider(),
                    event_bus=EventBus(),
                    refresh_areas_fn=lambda _file_path: None,
                    ui_access_manager=SimpleNamespace(
                        is_allowed=lambda _feature: allowed["value"]
                    ),
                    get_page_fn=lambda uid, pages={}: pages.setdefault(uid, object()),
                )
                scale_requests = []
                custom_requests = []
                area_requests = []
                bar.scale_change_requested.connect(
                    lambda *args: scale_requests.append(tuple(args))
                )
                bar.custom_scale_requested.connect(
                    lambda *args: custom_requests.append(tuple(args))
                )
                bar.area_change_requested.connect(
                    lambda *args: area_requests.append(tuple(args))
                )
                try:
                    if blocker != "no_bid":
                        bar.load_bid_areas(
                            BidRef("db.mdb", "bid-1"),
                            areas=[BidArea("area-1", "bid-1", "", "Area 1", 0)],
                        )
                    if blocker != "no_page":
                        bar.load_page("page-1", 1.0, 1.0, "")
                    bar.set_interactive(blocker != "not_interactive")
                    custom_index = bar.scale_combo.count() - 1
                    bar.scale_combo.activated.emit(0)
                    bar.scale_combo.activated.emit(custom_index)
                    bar.area_combo.area_activated.emit("area-1")
                    self.assertEqual(scale_requests, [])
                    self.assertEqual(custom_requests, [])
                    self.assertEqual(area_requests, [])
                    allowed["value"] = True
                    if blocker == "access":
                        bar.load_bid_areas(
                            BidRef("db.mdb", "bid-1"),
                            areas=[BidArea("area-1", "bid-1", "", "Area 1", 0)],
                        )
                        bar.load_page("page-1", 1.0, 1.0, "")
                        bar.set_interactive(True)
                        bar.area_combo.area_activated.emit("area-1")
                        self.assertEqual(
                            area_requests, [("db.mdb", "page-1", "area-1")]
                        )
                finally:
                    bar.deleteLater()

    @classmethod
    def setUpClass(cls):
        cls.app = _master_data_support__app()

    def tearDown(self):
        self.app.processEvents()

    def test_page_settings_area_picker_saves_without_database_refresh(self):
        load_calls = []
        save_calls = []
        refresh_calls = []
        workspace_models = []
        area_events = []
        event_bus = EventBus()
        event_bus.subscribe(
            AppEvents.REMOTE_AREAS_CHANGED, lambda **event: area_events.append(event)
        )

        def load_areas(file_path, bid_uid):
            load_calls.append((file_path, bid_uid))
            if not refresh_calls:
                return []
            return [BidArea("area-2", "bid-1", "", "Area 2", 1)]

        def save_areas(
            file_path,
            bid_uid,
            changes,
            publish_database_refreshed_after_write=True,
        ):
            save_calls.append(
                (
                    file_path,
                    bid_uid,
                    changes,
                    {
                        "publish_database_refreshed_after_write": (
                            publish_database_refreshed_after_write
                        )
                    },
                )
            )
            return {"new_0": "area-2"}

        def refresh_areas(file_path, bid_uid, deleted_uids):
            refresh_calls.append((file_path, bid_uid, deleted_uids))
            return [BidArea("area-2", "bid-1", "", "Area 2", 1)]

        class CapturingPicker:
            def __init__(
                self,
                icon_provider,
                workspace_state_model,
                parent=None,
                bid_areas=None,
                save_fn=None,
                used_uids=None,
                used_uids_fn=None,
                on_saved_fn=None,
                bid_ref=None,
                *,
                save_async_fn=None,
            ):
                self._save_fn = save_fn
                self._on_saved_fn = on_saved_fn
                workspace_models.append(workspace_state_model)

            def set_interactive(self, _enabled):
                pass

            def get_selected_uid(self):
                return "area-2"

            def has_saved_changes(self):
                return True

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        def exec_picker(picker, _event_bus):
            picker._save_fn(SimpleNamespace(deleted_uids=[]))
            picker._on_saved_fn()
            return QtWidgets.QDialog.DialogCode.Accepted

        bar = _master_data_support_MasterPageSettingsBar(
            _master_data_support_FakeIconProvider(),
            event_bus=event_bus,
            load_areas_fn=load_areas,
            save_areas_fn=save_areas,
            refresh_areas_fn=refresh_areas,
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            get_page_fn=lambda uid, pages={}: pages.setdefault(uid, object()),
        )
        area_changes = []
        bar.area_change_requested.connect(
            lambda file_path, page_uid, area_uid: area_changes.append(
                (file_path, page_uid, area_uid)
            )
        )
        bar.load_bid_areas(BidRef("db.mdb", "bid-1"))
        bar.load_page("page-1", 1.0, 1.0, "")
        bar.set_interactive(True)
        try:
            from ost_visualizer.presentation.components import page_settings_bar

            old_dialog = page_settings_bar.BidAreaPickerDialog
            old_exec = page_settings_bar.exec_with_ost_blocking
            page_settings_bar.BidAreaPickerDialog = CapturingPicker
            page_settings_bar.exec_with_ost_blocking = exec_picker
            try:
                bar._on_area_browse()
            finally:
                page_settings_bar.BidAreaPickerDialog = old_dialog
                page_settings_bar.exec_with_ost_blocking = old_exec
            self.assertEqual(len(save_calls), 1)
            self.assertEqual(save_calls[0][:2], ("db.mdb", "bid-1"))
            self.assertEqual(
                save_calls[0][3]["publish_database_refreshed_after_write"], False
            )
            self.assertEqual(refresh_calls, [("db.mdb", "bid-1", ())])
            self.assertEqual(len(area_events), 1)
            self.assertEqual(area_events[0]["database_id"], "db.mdb")
            self.assertEqual(area_events[0]["bid_uid"], "bid-1")
            self.assertTrue(area_events[0]["local_completion"])
            self.assertTrue(area_events[0]["page_controls_projected"])
            self.assertEqual(load_calls, [("db.mdb", "bid-1")] * 2)
            self.assertEqual(workspace_models, [bar._workspace_state_model])
            self.assertEqual(bar.area_combo.get_current_area_uid(), "area-2")
            self.assertEqual(area_changes, [("db.mdb", "page-1", "area-2")])
        finally:
            bar.deleteLater()

    def test_page_settings_area_picker_ignores_callbacks_after_bid_is_cleared(self):
        save_calls = []
        refresh_calls = []

        class CapturingPicker:
            def __init__(
                self,
                icon_provider,
                workspace_state_model,
                parent=None,
                bid_areas=None,
                save_fn=None,
                used_uids=None,
                used_uids_fn=None,
                on_saved_fn=None,
                bid_ref=None,
                *,
                save_async_fn=None,
            ):
                self._save_fn = save_fn
                self._on_saved_fn = on_saved_fn

            def get_selected_uid(self):
                return "area-2"

            def has_saved_changes(self):
                return False

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        bar = _master_data_support_MasterPageSettingsBar(
            _master_data_support_FakeIconProvider(),
            event_bus=EventBus(),
            load_areas_fn=lambda _file_path, _bid_uid: [],
            save_areas_fn=lambda *args, **kwargs: save_calls.append((args, kwargs)),
            refresh_areas_fn=refresh_calls.append,
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            get_page_fn=lambda uid, pages={}: pages.setdefault(uid, object()),
        )
        bar.load_bid_areas(BidRef("db.mdb", "bid-1"))
        bar.load_page("page-1", 1.0, 1.0, "")
        bar.set_interactive(True)

        def exec_picker(picker, _event_bus):
            bar.clear_bid()
            self.assertIsNone(picker._save_fn(object()))
            picker._on_saved_fn()
            return QtWidgets.QDialog.DialogCode.Accepted

        try:
            from ost_visualizer.presentation.components import page_settings_bar

            old_dialog = page_settings_bar.BidAreaPickerDialog
            old_exec = page_settings_bar.exec_with_ost_blocking
            page_settings_bar.BidAreaPickerDialog = CapturingPicker
            page_settings_bar.exec_with_ost_blocking = exec_picker
            try:
                bar._on_area_browse()
            finally:
                page_settings_bar.BidAreaPickerDialog = old_dialog
                page_settings_bar.exec_with_ost_blocking = old_exec
            self.assertEqual(save_calls, [])
            self.assertEqual(refresh_calls, [])
            self.assertIsNone(bar._bid_ref)
        finally:
            bar.deleteLater()

    def test_page_settings_area_picker_stops_after_bar_is_destroyed(self):
        bar = _master_data_support_MasterPageSettingsBar(
            _master_data_support_FakeIconProvider(),
            event_bus=EventBus(),
            load_areas_fn=lambda _file_path, _bid_uid: [],
            save_areas_fn=lambda *_args, **_kwargs: {},
            refresh_areas_fn=lambda _file_path: self.fail(
                "destroyed page settings must not refresh areas"
            ),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            get_page_fn=lambda uid, pages={}: pages.setdefault(uid, object()),
        )
        bar.load_bid_areas(BidRef("db.mdb", "bid-1"))
        bar.load_page("page-1", 1.0, 1.0, "")
        bar.set_interactive(True)
        picker_cleanups = []

        class DestroyingPicker(QtWidgets.QDialog):
            def __init__(self, *_args, parent=None, **_kwargs):
                super().__init__(None)

            def get_selected_uid(self):
                raise AssertionError("destroyed area picker must not be read")

            def has_saved_changes(self):
                raise AssertionError("destroyed area picker must not be read")

            def cleanup(self):
                picker_cleanups.append(True)

        def execute(picker, _event_bus):
            delete(bar)
            return QtWidgets.QDialog.DialogCode.Accepted

        with (
            patch(
                "ost_visualizer.presentation.components.page_settings_bar."
                "BidAreaPickerDialog",
                DestroyingPicker,
            ),
            patch(
                "ost_visualizer.presentation.components.page_settings_bar."
                "exec_with_ost_blocking",
                side_effect=execute,
            ),
        ):
            bar._on_area_browse()
        self.assertEqual(picker_cleanups, [True])

    def test_page_settings_area_picker_uses_async_save_without_sync_refresh(self):
        async_calls = []
        sync_calls = []
        refresh_calls = []

        class CapturingPicker:
            def __init__(
                self,
                icon_provider,
                workspace_state_model,
                parent=None,
                bid_areas=None,
                save_fn=None,
                used_uids=None,
                used_uids_fn=None,
                on_saved_fn=None,
                bid_ref=None,
                *,
                save_async_fn=None,
            ):
                self._save_async_fn = save_async_fn
                self._on_saved_fn = on_saved_fn

            def get_selected_uid(self):
                return "area-2"

            def has_saved_changes(self):
                return True

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        def save_async(bid_ref, changes, completed):
            async_calls.append((bid_ref, changes))
            completed(True, {"new-0": "area-2"})
            return True

        def exec_picker(picker, _event_bus):
            self.assertTrue(
                picker._save_async_fn(
                    {"new": [{"uid": "new-0", "name": "Area 2"}]},
                    lambda _success, _uid_map: None,
                )
            )
            picker._on_saved_fn()
            return QtWidgets.QDialog.DialogCode.Accepted

        area = BidArea("area-2", "bid-1", "", "Area 2", 1)
        bar = _master_data_support_MasterPageSettingsBar(
            _master_data_support_FakeIconProvider(),
            event_bus=EventBus(),
            load_areas_fn=lambda _file_path, _bid_uid: [area],
            save_areas_fn=lambda *args, **kwargs: sync_calls.append((args, kwargs)),
            save_areas_async_fn=save_async,
            refresh_areas_fn=refresh_calls.append,
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            get_page_fn=lambda uid, pages={}: pages.setdefault(uid, object()),
        )
        bar.load_bid_areas(BidRef("sql-database", "bid-1"))
        bar.load_page("page-1", 1.0, 1.0, "")
        bar.set_interactive(True)
        try:
            from ost_visualizer.presentation.components import page_settings_bar

            old_dialog = page_settings_bar.BidAreaPickerDialog
            old_exec = page_settings_bar.exec_with_ost_blocking
            page_settings_bar.BidAreaPickerDialog = CapturingPicker
            page_settings_bar.exec_with_ost_blocking = exec_picker
            try:
                bar._on_area_browse()
            finally:
                page_settings_bar.BidAreaPickerDialog = old_dialog
                page_settings_bar.exec_with_ost_blocking = old_exec
            self.assertEqual(len(async_calls), 1)
            self.assertEqual(async_calls[0][0], BidRef("sql-database", "bid-1"))
            self.assertEqual(
                async_calls[0][1], {"new": [{"uid": "new-0", "name": "Area 2"}]}
            )
            self.assertEqual(sync_calls, [])
            self.assertEqual(refresh_calls, [])
            self.assertEqual(bar.area_combo.get_current_area_uid(), "area-2")
        finally:
            bar.deleteLater()

    def test_page_settings_area_picker_uses_sync_save_when_database_is_not_async(self):
        captured = {}
        sync_calls = []
        async_calls = []

        class CapturingPicker:
            def __init__(
                self,
                icon_provider,
                workspace_state_model,
                parent=None,
                bid_areas=None,
                save_fn=None,
                used_uids=None,
                used_uids_fn=None,
                on_saved_fn=None,
                bid_ref=None,
                *,
                save_async_fn=None,
            ):
                captured["save_fn"] = save_fn
                captured["save_async_fn"] = save_async_fn

            def get_selected_uid(self):
                return None

            def has_saved_changes(self):
                return False

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        def exec_picker(picker, _event_bus):
            return QtWidgets.QDialog.DialogCode.Rejected

        bar = _master_data_support_MasterPageSettingsBar(
            _master_data_support_FakeIconProvider(),
            event_bus=EventBus(),
            load_areas_fn=lambda _file_path, _bid_uid: [],
            save_areas_fn=lambda *args, **kwargs: sync_calls.append((args, kwargs)),
            save_areas_async_fn=lambda *args: async_calls.append(args),
            uses_async_areas_fn=lambda file_path: file_path == "sql-database",
            refresh_areas_fn=lambda *_args: [],
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            get_page_fn=lambda uid, pages={}: pages.setdefault(uid, object()),
        )
        bar.load_bid_areas(BidRef("local.mdb", "bid-1"))
        bar.load_page("page-1", 1.0, 1.0, "")
        bar.set_interactive(True)
        try:
            with (
                patch(
                    "ost_visualizer.presentation.components.page_settings_bar."
                    "BidAreaPickerDialog",
                    CapturingPicker,
                ),
                patch(
                    "ost_visualizer.presentation.components.page_settings_bar."
                    "exec_with_ost_blocking",
                    exec_picker,
                ),
            ):
                bar._on_area_browse()
            self.assertIsNotNone(captured["save_fn"])
            self.assertIsNone(captured["save_async_fn"])
            self.assertEqual(async_calls, [])
        finally:
            bar.deleteLater()

    def test_page_settings_area_picker_refresh_failure_warns_and_keeps_area(self):
        area_events = []
        event_bus = EventBus()
        event_bus.subscribe(
            AppEvents.REMOTE_AREAS_CHANGED, lambda **event: area_events.append(event)
        )
        captured = {}
        results = []

        class CapturingPicker:
            def __init__(
                self,
                icon_provider,
                workspace_state_model,
                parent=None,
                bid_areas=None,
                save_fn=None,
                used_uids=None,
                used_uids_fn=None,
                on_saved_fn=None,
                bid_ref=None,
                *,
                save_async_fn=None,
            ):
                captured["save_fn"] = save_fn
                captured["on_saved_fn"] = on_saved_fn

            def get_selected_uid(self):
                return "area-2"

            def has_saved_changes(self):
                return True

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        def exec_picker(picker, _event_bus):
            results.append(captured["save_fn"](SimpleNamespace(deleted_uids=[])))
            captured["on_saved_fn"]()
            return QtWidgets.QDialog.DialogCode.Accepted

        bar = _master_data_support_MasterPageSettingsBar(
            _master_data_support_FakeIconProvider(),
            event_bus=event_bus,
            load_areas_fn=lambda _file_path, _bid_uid: [
                BidArea("area-1", "bid-1", "", "Area 1", 0)
            ],
            save_areas_fn=lambda *args, **kwargs: {"new_0": "area-2"},
            refresh_areas_fn=lambda *_args: None,
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            get_page_fn=lambda uid, pages={}: pages.setdefault(uid, object()),
        )
        area_changes = []
        bar.area_change_requested.connect(lambda *args: area_changes.append(args))
        bar.load_bid_areas(BidRef("db.mdb", "bid-1"))
        bar.load_page("page-1", 1.0, 1.0, "area-1")
        bar.set_interactive(True)
        try:
            with (
                patch(
                    "ost_visualizer.presentation.components.page_settings_bar."
                    "BidAreaPickerDialog",
                    CapturingPicker,
                ),
                patch(
                    "ost_visualizer.presentation.components.page_settings_bar."
                    "exec_with_ost_blocking",
                    exec_picker,
                ),
                patch(
                    "ost_visualizer.presentation.components.page_settings_bar."
                    "show_warning"
                ) as warning,
            ):
                bar._on_area_browse()
            warning.assert_called_once()
            self.assertEqual(warning.call_args.args[1], "Bid Areas")
            self.assertTrue(results[0].write_success)
            self.assertFalse(results[0].reload_success)
            self.assertEqual(area_events, [])
            self.assertEqual(area_changes, [])
            self.assertEqual(bar.area_combo.get_current_area_uid(), "area-1")
        finally:
            bar.deleteLater()
