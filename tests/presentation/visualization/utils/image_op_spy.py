from contextlib import contextmanager
from unittest import mock
from PySide6.QtGui import QImage, QPainter


@contextmanager
def recorded_image_operations():
    operations = []
    originals = {
        "convertToFormat": QImage.convertToFormat,
        "copy": QImage.copy,
        "invertPixels": QImage.invertPixels,
        "fillRect": QPainter.fillRect,
    }

    def image_pixels(image):
        return image.width() * image.height()

    def convert_to_format(image, *args, **kwargs):
        operations.append(("convertToFormat", image_pixels(image)))
        return originals["convertToFormat"](image, *args, **kwargs)

    def copy(image, *args, **kwargs):
        if args:
            rect = args[0]
            if isinstance(args[0], int):
                pixels = args[2] * args[3]
            else:
                pixels = round(rect.width() * rect.height())
        else:
            pixels = image_pixels(image)
        operations.append(("copy", pixels))
        return originals["copy"](image, *args, **kwargs)

    def invert_pixels(image, *args, **kwargs):
        operations.append(("invertPixels", image_pixels(image)))
        return originals["invertPixels"](image, *args, **kwargs)

    def fill_rect(painter, *args, **kwargs):
        rect = args[0]
        operations.append(("fillRect", round(rect.width() * rect.height())))
        return originals["fillRect"](painter, *args, **kwargs)

    with mock.patch.object(
        QImage, "convertToFormat", convert_to_format
    ), mock.patch.object(QImage, "copy", copy), mock.patch.object(
        QImage, "invertPixels", invert_pixels
    ), mock.patch.object(
        QPainter, "fillRect", fill_rect
    ):
        yield operations


def largest_operation(operations):
    return max((pixels for _name, pixels in operations), default=0)
