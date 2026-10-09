import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets
from ost_visualizer.presentation.utils.theme import (
    ActiveIndicatorStyle,
    configure_application_style,
)

Element = QtWidgets.QStyle.PrimitiveElement
Group = QtGui.QPalette.ColorGroup


class _Recorder(QtWidgets.QProxyStyle):
    def __init__(self, seen):
        super().__init__(QtWidgets.QStyleFactory.create("Fusion"))
        self.setObjectName("fusion")
        self._seen = seen

    def drawPrimitive(self, element, option, painter, widget=None):
        self._seen.append((element, option.palette.currentColorGroup(), option.state))
        super().drawPrimitive(element, option, painter, widget)


class ActiveIndicatorStyleTests(unittest.TestCase):
    def setUp(self):
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.seen = []
        self.style = ActiveIndicatorStyle(_Recorder(self.seen))

    def draw(self, element, group):
        option = (
            QtWidgets.QStyleOptionViewItem()
            if element == Element.PE_IndicatorItemViewItemCheck
            else QtWidgets.QStyleOptionButton()
        )
        option.rect = QtCore.QRect(0, 0, 16, 16)
        option.state = QtWidgets.QStyle.StateFlag.State_On
        palette = QtGui.QPalette(self.app.palette())
        palette.setCurrentColorGroup(group)
        option.palette = palette
        image = QtGui.QImage(16, 16, QtGui.QImage.Format.Format_ARGB32)
        painter = QtGui.QPainter(image)
        self.style.drawPrimitive(element, option, painter)
        painter.end()
        return option

    def test_indicators_in_inactive_windows_draw_with_the_active_colours(self):
        for element in (
            Element.PE_IndicatorCheckBox,
            Element.PE_IndicatorRadioButton,
            Element.PE_IndicatorItemViewItemCheck,
        ):
            with self.subTest(element=element.name):
                self.seen.clear()
                option = self.draw(element, Group.Inactive)
                self.assertEqual(self.seen[0][:2], (element, Group.Active))
                self.assertEqual(option.palette.currentColorGroup(), Group.Inactive)

    def test_disabled_indicators_and_other_elements_are_left_alone(self):
        self.draw(Element.PE_IndicatorCheckBox, Group.Disabled)
        self.draw(Element.PE_FrameFocusRect, Group.Inactive)
        self.draw(Element.PE_IndicatorCheckBox, Group.Active)
        self.assertEqual(
            [(element, group) for element, group, _state in self.seen[:1]]
            + [(e, g) for e, g, _s in self.seen if e == Element.PE_FrameFocusRect][:1]
            + [(e, g) for e, g, _s in self.seen if g == Group.Active][:1],
            [
                (Element.PE_IndicatorCheckBox, Group.Disabled),
                (Element.PE_FrameFocusRect, Group.Inactive),
                (Element.PE_IndicatorCheckBox, Group.Active),
            ],
        )

    def test_the_wrapped_style_keeps_its_name_and_is_installed_once(self):
        self.assertEqual(self.style.objectName(), "fusion")
        previous = self.app.style().objectName()
        try:
            configure_application_style(self.app)
            installed = self.app.style()
            configure_application_style(self.app)
            self.assertIs(self.app.style(), installed)
            self.assertIsInstance(installed, ActiveIndicatorStyle)
            self.assertEqual(installed.objectName(), previous)
        finally:
            self.app.setStyle(previous)

    def test_a_style_without_a_factory_name_is_left_unwrapped(self):
        previous = self.app.style().objectName()
        unnamed = QtWidgets.QCommonStyle()
        try:
            self.app.setStyle(unnamed)
            configure_application_style(self.app)
            self.assertIs(self.app.style(), unnamed)
        finally:
            self.app.setStyle(previous)


if __name__ == "__main__":
    unittest.main()
