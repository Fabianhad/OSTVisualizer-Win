import unittest
from types import SimpleNamespace
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
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from shiboken6 import delete
from tests.helpers.workspace_state import with_workspace_state

PageSettingsBar = with_workspace_state(PageSettingsBar)


class _AllowPageSettingsAccess:
    @staticmethod
    def is_allowed(_feature):
        return True
