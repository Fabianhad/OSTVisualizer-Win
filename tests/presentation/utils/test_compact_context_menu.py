import unittest
from unittest.mock import patch
from ost_visualizer.presentation.utils.compact_context_menu import (
    COMPACT_CONTEXT_MENU_NEXT_TEXT as NEXT,
    COMPACT_CONTEXT_MENU_PREVIOUS_TEXT as PREVIOUS,
    populate_compact_context_menu,
)
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete


def numbers(start, stop):
    return [str(i) for i in range(start, stop)]


class CompactMenuContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_queued_overflow_requires_current_visible_menu_page(self):
        for transition in ("current", "replace", "close", "destroy"):
            with self.subTest(transition=transition):
                menu = QtWidgets.QMenu()
                callbacks = []

                def add(target, value):
                    return target.addAction(str(value))

                populate_compact_context_menu(menu, list(range(40)), add)
                menu.show()
                initial = [a.text() for a in menu.actions()]
                self.assertEqual(initial, numbers(0, 21) + [NEXT])
                overflow = menu.actions()[-1].defaultWidget()
                with patch.object(
                    QtCore.QTimer, "singleShot", lambda delay, fn: callbacks.append(fn)
                ):
                    overflow.click()
                if transition == "replace":
                    populate_compact_context_menu(menu, ["New target"], add)
                elif transition == "close":
                    menu.close()
                elif transition == "destroy":
                    delete(menu)
                try:
                    callbacks[0]()
                    if transition == "destroy":
                        continue
                    labels = [a.text() for a in menu.actions()]
                    if transition == "current":
                        self.assertEqual(labels, [PREVIOUS] + numbers(21, 40))
                    elif transition == "replace":
                        self.assertEqual(labels, ["New target"])
                    else:
                        self.assertEqual(labels, initial)
                finally:
                    if transition != "destroy":
                        delete(menu)
                    QtCore.QCoreApplication.sendPostedEvents(
                        None, QtCore.QEvent.Type.DeferredDelete
                    )

    def _populate_and_show(self, items, before_render=None):
        menu = QtWidgets.QMenu()
        self.addCleanup(delete, menu)
        populate_compact_context_menu(
            menu,
            items,
            lambda target, value: target.addAction(str(value)),
            before_render=before_render,
        )
        menu.show()
        return menu

    def _click_overflow(self, menu, position):
        callbacks = []
        overflow = menu.actions()[position].defaultWidget()
        with patch.object(
            QtCore.QTimer, "singleShot", lambda delay, fn: callbacks.append(fn)
        ):
            overflow.click()
        self.assertEqual(len(callbacks), 1)
        callbacks[0]()

    def test_menu_within_row_limit_has_no_overflow_actions(self):
        menu = self._populate_and_show(list(range(22)))
        self.assertEqual([a.text() for a in menu.actions()], numbers(0, 22))
        self.assertEqual(
            [a for a in menu.actions() if isinstance(a, QtWidgets.QWidgetAction)], []
        )
        self.assertEqual(menu.property("ost_compact_overflow_item_count"), 22)
        self.assertEqual(menu.property("ost_compact_overflow_max_visible_rows"), 22)

    def test_menu_over_row_limit_pages_with_next_overflow_action(self):
        menu = self._populate_and_show(list(range(23)))
        self.assertEqual([a.text() for a in menu.actions()], numbers(0, 21) + [NEXT])
        self.assertEqual(menu.property("ost_compact_overflow_item_count"), 23)

    def test_previous_page_returns_to_first_page_and_before_render_runs_each_page(
        self,
    ):
        renders = []
        menu = self._populate_and_show(
            list(range(40)), before_render=lambda: renders.append("render")
        )
        self.assertEqual(renders, ["render"])
        self._click_overflow(menu, -1)
        self.assertEqual(
            [a.text() for a in menu.actions()], [PREVIOUS] + numbers(21, 40)
        )
        clicks = 0
        while menu.actions()[0].text() == PREVIOUS:
            left_page = [a.text() for a in menu.actions()]
            first_left_item = int(left_page[1])
            self._click_overflow(menu, 0)
            clicks += 1
            # Going back must not skip the item just before the page left.
            self.assertIn(str(first_left_item - 1), [a.text() for a in menu.actions()])
            self.assertLessEqual(len(menu.actions()), 22)
            self.assertLess(clicks, 5)
        self.assertEqual([a.text() for a in menu.actions()], numbers(0, 21) + [NEXT])
        self.assertEqual(renders, ["render"] * (2 + clicks))

    def test_forward_paging_reaches_every_item_in_order_within_row_limit(self):
        menu = self._populate_and_show(list(range(60)))
        pages = [[a.text() for a in menu.actions()]]
        while pages[-1][-1] == NEXT:
            self._click_overflow(menu, -1)
            pages.append([a.text() for a in menu.actions()])
            self.assertLess(len(pages), 6)
        self.assertEqual(
            [len(page) <= 22 for page in pages], [True] * len(pages), pages
        )
        self.assertEqual(pages[1][0], PREVIOUS)
        self.assertEqual(pages[-1][0], PREVIOUS)
        self.assertEqual(pages[-1][-1], "59")
        seen = []
        for page in pages:
            seen.extend(int(text) for text in page if text not in (PREVIOUS, NEXT))
        self.assertEqual(sorted(set(seen)), list(range(60)))
        self.assertEqual(seen, sorted(seen))
