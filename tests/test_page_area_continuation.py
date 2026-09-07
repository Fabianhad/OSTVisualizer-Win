import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete
from ost_visualizer.domain.entities.area import BidArea
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.components.page_settings_bar import PageSettingsBar
from tests.workspace_state_test_support import make_workspace_state_model


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
                    load = Mock(return_value=areas)
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
                                if transition in ("current", "same_page_projection")
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
                    finally:
                        delete(bar)
                        QtCore.QCoreApplication.sendPostedEvents(
                            None, QtCore.QEvent.Type.DeferredDelete
                        )
