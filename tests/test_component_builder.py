import unittest
from types import SimpleNamespace
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.builders.component_builder import (
    _PlanRibbonToolBar,
    _PlanToolbarLayoutSyncFilter,
    _TakeoffViewSelectorController,
)
from ost_visualizer.presentation.components.page_settings_bar import PageSettingsBar
from ost_visualizer.presentation.components.popup_tracking_combo import (
    PopupTrackingComboBox,
    parse_zoom_percent,
    update_zoom_combo,
)
from ost_visualizer.presentation.components.toolbar_overflow import (
    PageSettingsOverflowWidget,
    SyncedComboOverflowWidget,
    add_overflow_widget,
)
from ost_visualizer.presentation.windows.mesh_view_window import MeshViewWindow


class _AllowPageSettingsAccess:
    @staticmethod
    def is_allowed(_feature):
        return True


class ComponentBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_plan_toolbar_layout_filter_coalesces_event_burst(self):
        calls = []
        watched = QtCore.QObject()
        sync_filter = _PlanToolbarLayoutSyncFilter(lambda: calls.append("sync"))
        for event_type in (
            QtCore.QEvent.Type.Show,
            QtCore.QEvent.Type.Resize,
            QtCore.QEvent.Type.LayoutRequest,
        ):
            sync_filter.eventFilter(watched, QtCore.QEvent(event_type))
        self.assertEqual(calls, [])
        self.app.processEvents()
        self.assertEqual(calls, ["sync"])
        sync_filter.eventFilter(
            watched, QtCore.QEvent(QtCore.QEvent.Type.LayoutRequest)
        )
        self.app.processEvents()
        self.assertEqual(calls, ["sync", "sync"])

    def test_plan_ribbon_toolbar_honors_preferred_vertical_docked_height(self):
        host = QtWidgets.QMainWindow()
        toolbar = _PlanRibbonToolBar(host)
        toolbar.setOrientation(QtCore.Qt.Orientation.Vertical)
        host.addToolBar(QtCore.Qt.ToolBarArea.RightToolBarArea, toolbar)
        toolbar.set_preferred_docked_height(240)
        self.assertGreaterEqual(toolbar.sizeHint().height(), 240)
        self.assertGreaterEqual(toolbar.minimumSizeHint().height(), 240)

    def _overflow_toolbar(self):
        host = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QtWidgets.QToolBar(host)
        layout.addWidget(toolbar)
        for index in range(3):
            toolbar.addAction(f"Action {index}")
        host.resize(800, 100)
        host.show()
        self.app.processEvents()
        return host, toolbar

    def _use_extension_menu(self, toolbar, callback):
        extension = toolbar.findChild(QtWidgets.QToolButton, "qt_toolbar_ext_button")
        self.assertIsNotNone(extension)
        self.assertTrue(extension.isVisible())
        observed = []

        def inspect_and_close():
            menus = [
                widget
                for widget in self.app.topLevelWidgets()
                if isinstance(widget, QtWidgets.QMenu) and widget.isVisible()
            ]
            self.assertEqual(len(menus), 1)
            observed.append(callback(menus[0]))
            menus[0].close()

        QtCore.QTimer.singleShot(0, inspect_and_close)
        extension.click()
        self.app.processEvents()
        self.assertEqual(len(observed), 1)
        return observed[0]

    def test_native_toolbar_overflow_exposes_synced_combo_widget(self):
        host, toolbar = self._overflow_toolbar()
        source = QtWidgets.QComboBox()
        source.addItems(["100%", "125%", "150%"])
        source.setCurrentIndex(1)
        activations = []

        def activate(index):
            source.setCurrentIndex(index)
            activations.append(index)

        action = add_overflow_widget(
            toolbar,
            source,
            overflow_factory=lambda parent: SyncedComboOverflowWidget(
                source, "Zoom", activate, parent
            ),
            text="Zoom",
        )
        host.resize(1200, 100)
        self.app.processEvents()
        self.assertIs(toolbar.widgetForAction(action), source)
        self.assertTrue(toolbar.widgetForAction(action).isVisible())

        host.resize(180, 100)
        self.app.processEvents()
        self.assertFalse(toolbar.widgetForAction(action).isVisible())

        def use_combo(menu):
            combo = menu.findChild(
                QtWidgets.QComboBox, "takeoffToolbarOverflowZoomCombo"
            )
            self.assertIsNotNone(combo)
            self.assertEqual(combo.currentText(), "125%")
            combo.setCurrentIndex(2)
            combo.activated.emit(2)
            return combo.currentText()

        self.assertEqual(self._use_extension_menu(toolbar, use_combo), "150%")
        self.assertEqual(source.currentText(), "150%")
        self.assertEqual(activations, [2])

        host.resize(800, 100)
        self.app.processEvents()
        self.assertTrue(toolbar.widgetForAction(action).isVisible())
        self.assertEqual(source.currentText(), "150%")
        host.close()

    def test_toolbar_uses_canonical_widget_without_creating_overflow_proxy(self):
        host, toolbar = self._overflow_toolbar()
        for index in range(12):
            toolbar.addAction(f"Extra action {index}")
        host.resize(80, 100)
        self.app.processEvents()
        source = QtWidgets.QComboBox()
        source.addItems(["100%", "125%"])
        factory_parents = []

        def create_overflow_widget(parent):
            factory_parents.append(parent)
            return SyncedComboOverflowWidget(
                source,
                "Zoom",
                source.setCurrentIndex,
                parent,
            )

        action = add_overflow_widget(
            toolbar,
            source,
            overflow_factory=create_overflow_widget,
            text="Zoom",
        )

        self.assertEqual(factory_parents, [])
        self.assertIs(toolbar.widgetForAction(action), source)
        self.assertIs(source.parentWidget(), toolbar)
        self.assertFalse(source.isWindow())
        host.close()

    def test_overflow_combo_tracks_source_state_and_disabled_state(self):
        host, toolbar = self._overflow_toolbar()
        for index in range(8):
            toolbar.addAction(f"Overflow action {index}")
        source = QtWidgets.QComboBox()
        source.addItems(["One", "Two"])
        visibility_action = QtGui.QAction("Page", host)
        add_overflow_widget(
            toolbar,
            source,
            overflow_factory=lambda parent: SyncedComboOverflowWidget(
                source,
                "Page",
                lambda index: source.setCurrentIndex(index),
                parent,
            ),
            text="Page",
            visibility_action=visibility_action,
        )
        host.resize(180, 100)
        source.setCurrentIndex(1)
        source.setEnabled(False)
        self.app.processEvents()

        def inspect(menu):
            combo = menu.findChild(
                QtWidgets.QComboBox, "takeoffToolbarOverflowPageCombo"
            )
            self.assertIsNotNone(combo)
            return combo.currentText(), combo.isEnabled()

        self.assertEqual(self._use_extension_menu(toolbar, inspect), ("Two", False))
        visibility_action.setVisible(False)
        self.app.processEvents()

        def hidden_inspect(menu):
            combo = menu.findChild(
                QtWidgets.QComboBox, "takeoffToolbarOverflowPageCombo"
            )
            return combo is not None and combo.isVisible()

        self.assertFalse(self._use_extension_menu(toolbar, hidden_inspect))
        host.close()

    def test_overflow_action_button_uses_the_canonical_action_once(self):
        host, toolbar = self._overflow_toolbar()
        triggered = []
        command = QtGui.QAction("Dimension", host)
        command.triggered.connect(lambda: triggered.append("dimension"))
        toolbar_button = QtWidgets.QToolButton()
        toolbar_button.setDefaultAction(command)

        def create_button(parent):
            button = QtWidgets.QToolButton(parent)
            button.setObjectName("takeoffToolbarOverflowDimensionButton")
            button.setDefaultAction(command)
            return button

        action = add_overflow_widget(
            toolbar,
            toolbar_button,
            overflow_factory=create_button,
            text=command.text(),
        )
        self.assertIs(toolbar.widgetForAction(action), toolbar_button)
        self.assertIs(toolbar_button.parentWidget(), toolbar)
        self.assertFalse(toolbar_button.isWindow())
        host.resize(180, 100)
        self.app.processEvents()

        def trigger(menu):
            button = menu.findChild(
                QtWidgets.QToolButton,
                "takeoffToolbarOverflowDimensionButton",
            )
            self.assertIsNotNone(button)
            button.click()

        for _ in range(3):
            self._use_extension_menu(toolbar, trigger)
        self.assertEqual(triggered, ["dimension", "dimension", "dimension"])
        host.close()

    def test_page_settings_overflow_uses_canonical_signals_and_values(self):
        source = PageSettingsBar(
            icon_provider=None,
            event_bus=None,
            refresh_areas_fn=lambda *_args: None,
            ui_access_manager=_AllowPageSettingsAccess(),
        )
        bid_ref = BidRef("example.mdb", "bid-1")
        source.load_bid_areas(
            bid_ref,
            areas=[
                BidArea("a1", "bid-1", "", "First Floor", 0),
                BidArea("a2", "bid-1", "a1", "Lobby", 0),
            ],
        )
        source.load_page("page-1", 1.0, 48.0, "a1")
        source.set_interactive(True)
        scale_requests = []
        area_requests = []
        source.scale_change_requested.connect(
            lambda *_args: scale_requests.append(_args)
        )
        source.area_change_requested.connect(lambda *_args: area_requests.append(_args))
        overflow = PageSettingsOverflowWidget(source)

        scale_index = next(
            index
            for index in range(overflow.scale_combo.count())
            if overflow.scale_combo.itemData(index) == (1.0, 120.0)
        )
        overflow.scale_combo.setCurrentIndex(scale_index)
        overflow.scale_combo.activated.emit(scale_index)
        area_index = overflow.area_combo.findData("a2")
        overflow.area_combo.setCurrentIndex(area_index)
        overflow.area_combo.activated.emit(area_index)

        self.assertEqual(source.scale_combo.currentIndex(), scale_index)
        self.assertEqual(source.area_combo.get_current_area_uid(), "a2")
        self.assertEqual(len(scale_requests), 1)
        self.assertEqual(len(area_requests), 1)
        self.assertEqual(overflow.area_combo.currentData(), "a2")

        presentation_updates = []
        source.presentation_state_changed.connect(
            lambda: presentation_updates.append(None)
        )
        source.load_page(
            "page-1",
            1.0,
            48.0,
            "a1",
            areas_with_takeoff={"a1"},
        )
        self.assertEqual(presentation_updates, [None])
        self.assertEqual(overflow.area_combo.currentData(), "a1")
        source.set_interactive(False)
        self.assertFalse(overflow.scale_combo.isEnabled())
        self.assertFalse(overflow.area_combo.isEnabled())
        self.assertFalse(overflow.area_browse_button.isEnabled())
        overflow.deleteLater()
        source.deleteLater()

    def test_native_overflow_hosts_page_settings_combos(self):
        host, toolbar = self._overflow_toolbar()
        source = PageSettingsBar(
            icon_provider=None,
            event_bus=None,
            refresh_areas_fn=lambda *_args: None,
            ui_access_manager=_AllowPageSettingsAccess(),
        )
        action = add_overflow_widget(
            toolbar,
            source,
            overflow_factory=lambda parent: PageSettingsOverflowWidget(source, parent),
            text="Page settings",
        )
        host.resize(1200, 100)
        self.app.processEvents()
        self.assertIs(toolbar.widgetForAction(action), source)
        self.assertIs(source.parentWidget(), toolbar)
        self.assertFalse(source.isWindow())
        self.assertEqual(source.scale_combo.y(), source.area_combo.y())

        host.resize(180, 100)
        self.app.processEvents()
        self.assertFalse(toolbar.widgetForAction(action).isVisible())

        def inspect(menu):
            scale = menu.findChild(
                QtWidgets.QComboBox, "takeoffToolbarOverflowScaleCombo"
            )
            area = menu.findChild(
                QtWidgets.QComboBox, "takeoffToolbarOverflowAreaCombo"
            )
            return (
                scale is not None and scale.isVisible(),
                area is not None and area.isVisible(),
            )

        self.assertEqual(self._use_extension_menu(toolbar, inspect), (True, True))
        host.close()

    def test_overflow_combo_accepts_keyboard_activation(self):
        source = QtWidgets.QComboBox()
        source.addItems(["One", "Two"])
        activations = []

        def activate(index):
            source.setCurrentIndex(index)
            activations.append(index)

        overflow = SyncedComboOverflowWidget(source, "Page", activate)
        overflow.show()
        overflow.combo.setFocus()
        QtTest.QTest.keyClick(overflow.combo, QtCore.Qt.Key.Key_Down)
        QtTest.QTest.keyClick(overflow.combo, QtCore.Qt.Key.Key_Enter)
        self.app.processEvents()
        self.assertEqual(source.currentIndex(), 1)
        self.assertEqual(activations, [1])
        overflow.close()

    def _view_selector(
        self,
        current_index=0,
        *,
        view_3d_visible=True,
        view_2d_visible=True,
    ):
        host = QtWidgets.QWidget()
        host.resize(400, 300)
        layout = QtWidgets.QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QtWidgets.QToolBar(host)
        view_3d_action = toolbar.addWidget(QtWidgets.QToolButton())
        view_2d_action = toolbar.addWidget(QtWidgets.QToolButton())
        view_3d_action.setVisible(view_3d_visible)
        view_2d_action.setVisible(view_2d_visible)
        view_stack = QtWidgets.QStackedWidget(host)
        view_3d = QtWidgets.QWidget()
        view_2d = QtWidgets.QWidget()
        view_stack.addWidget(view_3d)
        view_stack.addWidget(view_2d)
        view_stack.setCurrentIndex(current_index)
        layout.addWidget(toolbar)
        layout.addWidget(view_stack, 1)
        controller = _TakeoffViewSelectorController(
            toolbar,
            view_stack,
            view_3d_action,
            view_2d_action,
        )
        host.show()
        self.app.processEvents()
        return SimpleNamespace(
            host=host,
            toolbar=toolbar,
            view_stack=view_stack,
            view_3d=view_3d,
            view_2d=view_2d,
            view_3d_action=view_3d_action,
            view_2d_action=view_2d_action,
            controller=controller,
        )

    def test_view_selector_initial_availability_matrix(self):
        for view_3d_visible, view_2d_visible, initial_index, expected in (
            (True, True, 1, (True, 1)),
            (False, True, 0, (False, 1)),
            (True, False, 1, (False, 0)),
            (False, False, 1, (False, 1)),
        ):
            with self.subTest(
                view_3d_visible=view_3d_visible,
                view_2d_visible=view_2d_visible,
            ):
                ui = self._view_selector(
                    current_index=initial_index,
                    view_3d_visible=view_3d_visible,
                    view_2d_visible=view_2d_visible,
                )
                self.assertEqual(ui.toolbar.isVisible(), expected[0])
                self.assertEqual(ui.view_stack.currentIndex(), expected[1])
                self.assertEqual(ui.view_stack.count(), 2)
                self.assertTrue(ui.view_stack.currentWidget().isVisible())
                ui.host.close()

    def test_view_selector_shows_only_when_both_views_are_available(self):
        ui = self._view_selector(current_index=0)
        both_views_height = ui.view_stack.height()
        self.assertTrue(ui.toolbar.isVisible())
        self.assertTrue(ui.view_3d.isVisible())
        ui.view_3d_action.setVisible(False)
        self.app.processEvents()
        self.assertFalse(ui.toolbar.isVisible())
        self.assertEqual(ui.view_stack.currentIndex(), 1)
        self.assertTrue(ui.view_2d.isVisible())
        self.assertGreater(ui.view_stack.height(), both_views_height)
        ui.view_3d_action.setVisible(True)
        self.app.processEvents()
        self.assertTrue(ui.toolbar.isVisible())
        self.assertEqual(ui.view_stack.currentIndex(), 1)
        ui.view_2d_action.setVisible(False)
        self.app.processEvents()
        self.assertFalse(ui.toolbar.isVisible())
        self.assertEqual(ui.view_stack.currentIndex(), 0)
        self.assertTrue(ui.view_3d.isVisible())
        ui.view_2d_action.setVisible(True)
        self.app.processEvents()
        self.assertTrue(ui.toolbar.isVisible())
        self.assertEqual(ui.view_stack.currentIndex(), 0)
        ui.host.close()

    def test_view_selector_handles_disabled_and_unavailable_views(self):
        ui = self._view_selector(current_index=1)
        changes = []
        ui.view_stack.currentChanged.connect(changes.append)
        ui.view_2d_action.setEnabled(False)
        self.assertFalse(ui.toolbar.isVisible())
        self.assertEqual(ui.view_stack.currentIndex(), 0)
        self.assertEqual(changes, [0])
        ui.view_3d_action.setEnabled(False)
        self.assertFalse(ui.toolbar.isVisible())
        self.assertEqual(ui.view_stack.currentIndex(), 0)
        self.assertEqual(changes, [0])
        ui.view_2d_action.setEnabled(True)
        self.assertFalse(ui.toolbar.isVisible())
        self.assertEqual(ui.view_stack.currentIndex(), 1)
        self.assertEqual(changes, [0, 1])
        ui.host.close()

    def test_view_selector_refresh_is_idempotent_and_preserves_valid_selection(self):
        ui = self._view_selector(current_index=1)
        changes = []
        ui.view_stack.currentChanged.connect(changes.append)
        for _ in range(5):
            ui.controller.refresh()
        self.assertTrue(ui.toolbar.isVisible())
        self.assertEqual(ui.view_stack.currentIndex(), 1)
        self.assertEqual(changes, [])
        ui.view_3d_action.setVisible(False)
        for _ in range(5):
            ui.controller.refresh()
        self.assertEqual(ui.view_stack.currentIndex(), 1)
        self.assertEqual(changes, [])
        ui.host.close()

    def test_zoom_percent_parser_rejects_invalid_and_non_finite_values(self):
        self.assertEqual(parse_zoom_percent(" 125% "), 125.0)
        for value in ("", "invalid", "0", "-5", "nan", "inf", "-inf"):
            with self.subTest(value=value):
                self.assertIsNone(parse_zoom_percent(value))

    def test_zoom_combo_update_ignores_invalid_factor_and_restores_signals(self):
        combo = PopupTrackingComboBox()
        combo.setEditable(True)
        combo.setEditText("100%")
        update_zoom_combo(combo, float("inf"))
        self.assertEqual(combo.currentText(), "100%")
        update_zoom_combo(combo, 1.25)
        self.assertEqual(combo.currentText(), "125%")
        self.assertFalse(combo.signalsBlocked())
        self.assertFalse(combo.lineEdit().signalsBlocked())
        combo.blockSignals(True)
        combo.lineEdit().blockSignals(True)
        update_zoom_combo(combo, 1.5)
        self.assertEqual(combo.currentText(), "150%")
        self.assertTrue(combo.signalsBlocked())
        self.assertTrue(combo.lineEdit().signalsBlocked())

    def test_detached_mesh_invalid_zoom_text_restores_current_zoom(self):
        combo = PopupTrackingComboBox()
        combo.setEditable(True)
        combo.setEditText("inf")
        zoom_writes = []
        window = MeshViewWindow.__new__(MeshViewWindow)
        window._zoom_combo = combo
        window.viewer = SimpleNamespace(
            get_zoom_percent=lambda: 250.0,
            set_zoom_percent=zoom_writes.append,
        )
        MeshViewWindow._on_zoom_text_entered(window)
        self.assertEqual(zoom_writes, [])
        self.assertEqual(combo.currentText(), "250%")

    def test_detached_mesh_ignored_tiny_zoom_displays_actual_zoom(self):
        combo = PopupTrackingComboBox()
        combo.setEditable(True)
        combo.setEditText("0.0000001")
        zoom_writes = []
        window = MeshViewWindow.__new__(MeshViewWindow)
        window._zoom_combo = combo
        window.viewer = SimpleNamespace(
            get_zoom_percent=lambda: 250.0,
            set_zoom_percent=zoom_writes.append,
        )
        MeshViewWindow._on_zoom_text_entered(window)
        self.assertEqual(zoom_writes, [0.0000001])
        self.assertEqual(combo.currentText(), "250%")

    def test_detached_mesh_ignored_zoom_button_displays_actual_zoom(self):
        combo = PopupTrackingComboBox()
        combo.setEditable(True)
        zoom_writes = []
        window = MeshViewWindow.__new__(MeshViewWindow)
        window._zoom_combo = combo
        window.viewer = SimpleNamespace(
            get_zoom_percent=lambda: 250.0,
            set_zoom_percent=zoom_writes.append,
        )
        MeshViewWindow._on_zoom_in(window)
        self.assertEqual(zoom_writes, [287.5])
        self.assertEqual(combo.currentText(), "250%")


if __name__ == "__main__":
    unittest.main()
