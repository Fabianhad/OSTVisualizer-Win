import unittest
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.components.page_settings_bar import PageSettingsBar
from ost_visualizer.presentation.components.toolbar_overflow import (
    PageSettingsOverflowWidget,
    SyncedComboOverflowWidget,
    add_overflow_widget,
)
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from tests.helpers.workspace_state import with_workspace_state
from tests.presentation.builders.component_widget_support import (
    PageSettingsBar as _component_widget_support_PageSettingsBar,
    _AllowPageSettingsAccess as _component_widget_support__AllowPageSettingsAccess,
)
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.components.toolbar_overflow import add_overflow_widget
from shiboken6 import delete, isValid
from tests.presentation.components.toolbar_visibility_support import (
    register_test_fonts as _toolbar_visibility_support_register_test_fonts,
)


class ToolbarOverflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

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
        failures = []

        def inspect_and_close():
            menus = [
                widget
                for widget in self.app.topLevelWidgets()
                if isinstance(widget, QtWidgets.QMenu) and widget.isVisible()
            ]
            try:
                self.assertEqual(len(menus), 1)
                observed.append(callback(menus[0]))
            except BaseException as error:
                failures.append(error)
            finally:
                for menu in menus:
                    menu.close()

        QtCore.QTimer.singleShot(0, inspect_and_close)
        extension.click()
        self.app.processEvents()
        if failures:
            raise failures[0]
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
        visibility_action.setVisible(True)
        self.app.processEvents()
        self.assertEqual(self._use_extension_menu(toolbar, inspect), ("Two", False))
        source.setEnabled(True)
        source.setCurrentIndex(0)
        self.app.processEvents()
        self.assertEqual(self._use_extension_menu(toolbar, inspect), ("One", True))
        host.close()

    def test_overflow_combo_resyncs_items_and_editable_text_from_source(self):
        source = QtWidgets.QComboBox()
        source.setEditable(True)
        source.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        source.addItems(["50%", "100%"])
        source.setCurrentIndex(1)
        submitted = []
        activations = []
        overflow = SyncedComboOverflowWidget(
            source,
            "Zoom",
            activations.append,
            on_text_submitted=submitted.append,
        )
        self.assertTrue(overflow.combo.isEditable())
        self.assertEqual(
            [overflow.combo.itemText(i) for i in range(overflow.combo.count())],
            ["50%", "100%"],
        )
        self.assertEqual(overflow.combo.currentText(), "100%")
        source.addItem("200%")
        self.assertEqual(overflow.combo.count(), 3)
        self.assertEqual(overflow.combo.itemText(2), "200%")
        source.setCurrentText("75%")
        self.assertEqual(overflow.combo.currentText(), "75%")
        overflow.combo.lineEdit().setText("33%")
        overflow.combo.lineEdit().returnPressed.emit()
        self.assertEqual(submitted, ["33%"])
        self.assertEqual(overflow.combo.currentText(), "75%")
        source.clear()
        self.assertEqual(overflow.combo.count(), 0)
        self.assertEqual(activations, [])
        overflow.deleteLater()
        source.deleteLater()

    def test_overflow_combo_without_text_callback_ignores_return_key(self):
        source = QtWidgets.QComboBox()
        source.setEditable(True)
        source.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        source.addItems(["50%", "100%"])
        overflow = SyncedComboOverflowWidget(source, "Zoom", lambda _index: None)
        overflow.combo.lineEdit().setText("33%")
        overflow.combo.lineEdit().returnPressed.emit()
        self.assertEqual(overflow.combo.currentText(), "33%")
        self.assertEqual(source.currentText(), "50%")
        overflow.deleteLater()
        source.deleteLater()

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
        source = _component_widget_support_PageSettingsBar(
            icon_provider=None,
            event_bus=None,
            refresh_areas_fn=lambda _file_path: None,
            ui_access_manager=_component_widget_support__AllowPageSettingsAccess(),
            get_page_fn=lambda uid, pages={}: pages.setdefault(uid, object()),
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
            lambda file_path, page_uid, sf1, sf2: scale_requests.append(
                (file_path, page_uid, sf1, sf2)
            )
        )
        source.area_change_requested.connect(
            lambda file_path, page_uid, area_uid: area_requests.append(
                (file_path, page_uid, area_uid)
            )
        )
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
        self.assertEqual(scale_requests, [("example.mdb", "page-1", 1.0, 120.0)])
        self.assertEqual(area_requests, [("example.mdb", "page-1", "a2")])
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
        source = _component_widget_support_PageSettingsBar(
            icon_provider=None,
            event_bus=None,
            refresh_areas_fn=lambda _file_path: None,
            ui_access_manager=_component_widget_support__AllowPageSettingsAccess(),
            get_page_fn=lambda uid, pages={}: pages.setdefault(uid, object()),
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


class TakeoffToolbarPreferencesTests(unittest.TestCase):
    _overflow_toolbar = ToolbarOverflowTests._overflow_toolbar
    _use_extension_menu = ToolbarOverflowTests._use_extension_menu

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        _toolbar_visibility_support_register_test_fonts()

    def test_overflow_hide_show_cycles_reuse_command_without_duplicate_signals(self):
        host, toolbar = self._overflow_toolbar()
        self.addCleanup(lambda: delete(host) if isValid(host) else None)
        command = QtGui.QAction("Select", host)
        calls = []
        command.triggered.connect(lambda: calls.append(True))

        def button(parent):
            result = QtWidgets.QToolButton(parent)
            result.setObjectName("visibilityOverflowButton")
            result.setDefaultAction(command)
            return result

        original = button(toolbar)
        wrapper = add_overflow_widget(
            toolbar,
            original,
            overflow_factory=button,
            text="Select",
            visibility_action=command,
        )
        original_actions = toolbar.actions()
        host.resize(180, 100)
        self.app.processEvents()

        def click(menu):
            proxy = menu.findChild(QtWidgets.QToolButton, "visibilityOverflowButton")
            self.assertIsNotNone(proxy)
            self.assertIs(proxy.defaultAction(), command)
            proxy.click()

        for cycle in range(5):
            wrapper.set_toolbar_visible(False)
            command.setEnabled(False)
            command.setEnabled(True)
            self.app.processEvents()
            self.assertFalse(wrapper.isVisible())
            wrapper.set_toolbar_visible(True)
            self.app.processEvents()
            self._use_extension_menu(toolbar, click)
            self.assertEqual(len(calls), cycle + 1)
            self.assertEqual(toolbar.actions(), original_actions)
            self.assertIs(toolbar.widgetForAction(wrapper), original)
            self.assertTrue(isValid(original))
        host.close()

    def test_disabled_command_stays_disabled_when_visibility_changes_in_open_overflow(
        self,
    ):
        host, toolbar = self._overflow_toolbar()
        self.addCleanup(lambda: delete(host) if isValid(host) else None)
        command = QtGui.QAction("Select", host)
        command.setEnabled(False)

        def button(parent):
            result = QtWidgets.QToolButton(parent)
            result.setDefaultAction(command)
            return result

        original = button(toolbar)
        wrapper = add_overflow_widget(
            toolbar,
            original,
            overflow_factory=button,
            text="Select",
            visibility_action=command,
        )
        host.resize(180, 100)
        self.app.processEvents()

        def inspect(menu):
            for _ in range(3):
                wrapper.set_toolbar_visible(False)
                wrapper.set_toolbar_visible(True)
                proxies = [
                    w for w in wrapper.createdWidgets() if w.parentWidget() is menu
                ]
                self.assertEqual(len(proxies), 1)
                self.assertFalse(proxies[0].isEnabled())
                self.assertFalse(original.isEnabled())
                self.assertIs(proxies[0].defaultAction(), command)

        self._use_extension_menu(toolbar, inspect)
        host.close()
