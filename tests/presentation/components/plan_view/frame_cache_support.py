import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache
from PySide6 import QtCore, QtGui


class FakeFrameCacheAdapter(PageCache):
    def file_signature(self, _file_path):
        return None

    def get_frame(
        self,
        file_path,
        page_index,
        scale,
        frame_x_pts,
        frame_y_pts,
        frame_w_pts,
        frame_h_pts,
        rotation,
        wait_for_in_flight=True,
    ):
        del wait_for_in_flight
        return self.render_frame_direct(
            file_path,
            page_index,
            scale,
            frame_x_pts,
            frame_y_pts,
            frame_w_pts,
            frame_h_pts,
            rotation,
        )


class FakeCompositeFramePageCache(FakeFrameCacheAdapter):
    def __init__(self, source_size=(100.0, 100.0)):
        super().__init__()
        self.calls = []
        self.source_size = source_size

    def render_frame_direct(
        self,
        file_path,
        page_index,
        scale,
        frame_x_pts,
        frame_y_pts,
        frame_w_pts,
        frame_h_pts,
        rotation,
    ):
        self.calls.append(
            (
                file_path,
                page_index,
                scale,
                frame_x_pts,
                frame_y_pts,
                frame_w_pts,
                frame_h_pts,
            )
        )
        return QtGui.QImage(
            max(1, math.ceil(frame_w_pts * scale)),
            max(1, math.ceil(frame_h_pts * scale)),
            QtGui.QImage.Format.Format_ARGB32,
        )

    def get_page_size(self, _file_path, _page_index):
        return self.source_size


class FakeOverlayMovementPageCache(FakeFrameCacheAdapter):
    def _source_image(
        self,
        scale,
        color,
    ):
        image = QtGui.QImage(
            max(1, math.ceil(100.0 * scale)),
            max(1, math.ceil(100.0 * scale)),
            QtGui.QImage.Format.Format_ARGB32,
        )
        image.fill(QtGui.QColor(255, 255, 255))
        painter = QtGui.QPainter(image)
        painter.setPen(color)
        painter.drawLine(0, 0, 0, image.height() - 1)
        painter.end()
        return image

    def get_page(
        self,
        _file_path,
        _page_index,
        scale,
        _rotation,
        wait_for_in_flight=True,
    ):
        del wait_for_in_flight
        return self._source_image(scale, QtGui.QColor(0, 0, 0))

    def get_tinted_page(
        self,
        _file_path,
        _page_index,
        scale,
        _rotation,
        tint_rgb=None,
        wait_for_in_flight=True,
    ):
        del wait_for_in_flight
        color = QtGui.QColor(*(tint_rgb or (0, 0, 0)))
        return self._source_image(scale, color)

    def get_page_size(self, _file_path, _page_index):
        return (100.0, 100.0)

    def render_frame_direct(
        self,
        file_path,
        page_index,
        scale,
        frame_x_pts,
        frame_y_pts,
        frame_w_pts,
        frame_h_pts,
        rotation,
    ):
        image = QtGui.QImage(
            max(1, math.ceil(frame_w_pts * scale)),
            max(1, math.ceil(frame_h_pts * scale)),
            QtGui.QImage.Format.Format_ARGB32,
        )
        image.fill(QtGui.QColor(255, 255, 255))
        if file_path == "overlay.pdf":
            painter = QtGui.QPainter(image)
            painter.setPen(QtGui.QColor(0, 0, 0))
            line_x = round((0.0 - frame_x_pts) * scale)
            if -1 <= line_x <= image.width():
                painter.drawLine(line_x, 0, line_x, image.height() - 1)
            painter.end()
        return image


class FakeShiftedSourceMarkerTifPageCache(FakeFrameCacheAdapter):
    def __init__(self):
        super().__init__()
        self.page_scales = []

    def get_page(
        self,
        _file_path,
        _page_index,
        scale,
        _rotation,
        wait_for_in_flight=True,
    ):
        del wait_for_in_flight
        self.page_scales.append(scale)
        width = max(1, math.ceil(100.0 * scale))
        height = max(1, math.ceil(100.0 * scale))
        image = QtGui.QImage(
            width,
            height,
            QtGui.QImage.Format.Format_ARGB32,
        )
        image.fill(QtGui.QColor(255, 255, 255))
        painter = QtGui.QPainter(image)
        painter.setPen(QtGui.QColor(0, 0, 0))
        marker_x = round(0.5 * width)
        painter.drawLine(marker_x, 0, marker_x, height - 1)
        painter.end()
        return image

    def get_page_size(self, _file_path, _page_index):
        return (100.0, 100.0)

    def render_frame_direct(
        self,
        file_path,
        page_index,
        scale,
        frame_x_pts,
        frame_y_pts,
        frame_w_pts,
        frame_h_pts,
        rotation,
    ):
        image = QtGui.QImage(
            max(1, math.ceil(frame_w_pts * scale)),
            max(1, math.ceil(frame_h_pts * scale)),
            QtGui.QImage.Format.Format_ARGB32,
        )
        image.fill(QtGui.QColor(255, 255, 255))
        if file_path == "base.pdf":
            painter = QtGui.QPainter(image)
            painter.setPen(QtGui.QColor(0, 0, 0))
            line_x = round((0.0 - frame_x_pts) * scale)
            if -1 <= line_x <= image.width():
                painter.drawLine(line_x, 0, line_x, image.height() - 1)
            painter.end()
        return image


class FakeDenseMarkerOverlayMovementPageCache(FakeOverlayMovementPageCache):
    def get_page(self, file_path, page_index, scale, rotation, wait_for_in_flight=True):
        image = super().get_page(
            file_path,
            page_index,
            scale,
            rotation,
            wait_for_in_flight=wait_for_in_flight,
        )
        if file_path == "overlay.tif":
            painter = QtGui.QPainter(image)
            painter.fillRect(
                QtCore.QRect(0, 0, max(1, image.width() // 2), image.height()),
                QtGui.QColor(0, 0, 0),
            )
            painter.end()
        return image

    def get_tinted_page(
        self,
        file_path,
        page_index,
        scale,
        rotation,
        tint_rgb=None,
        wait_for_in_flight=True,
    ):
        image = super().get_tinted_page(
            file_path,
            page_index,
            scale,
            rotation,
            tint_rgb=tint_rgb,
            wait_for_in_flight=wait_for_in_flight,
        )
        if file_path == "overlay.tif":
            painter = QtGui.QPainter(image)
            pen_color = QtGui.QColor(*tint_rgb) if tint_rgb else QtGui.QColor(0, 0, 0)
            painter.setPen(pen_color)
            painter.fillRect(
                QtCore.QRect(0, 0, max(1, image.width() // 2), image.height()),
                pen_color,
            )
            painter.end()
        return image
