from PySide6 import QtCore, QtGui


def rounded_color_swatch(
    color: QtGui.QColor,
    size: int,
    radius: int = 5,
) -> QtGui.QPixmap:
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.setBrush(QtGui.QBrush(color))
    inset = 1
    rect = QtCore.QRectF(
        inset,
        inset,
        max(0, size - inset * 2),
        max(0, size - inset * 2),
    )
    painter.drawRoundedRect(rect, radius, radius)
    painter.end()
    return pixmap
