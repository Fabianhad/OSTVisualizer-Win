import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.visualization.utils.image_bands import (
    BAND_PIXELS,
    convert_to_format,
    copy_image,
    copy_region,
    darkened_premultiplied,
    inverted_rgb,
)
from PySide6 import QtGui, QtWidgets
from tests.presentation.visualization.utils.image_op_spy import (
    largest_operation,
    recorded_image_operations,
)

ARGB32 = QtGui.QImage.Format.Format_ARGB32
PREMULTIPLIED = QtGui.QImage.Format.Format_ARGB32_Premultiplied
RGB32 = QtGui.QImage.Format.Format_RGB32
GRAYSCALE = QtGui.QImage.Format.Format_Grayscale8
SMALL = (37, 23)
LARGE = (997, 701)


def pattern_image(width, height, image_format=ARGB32):
    image = QtGui.QImage(width, height, image_format)
    destination = image.bits()
    size = len(destination)
    pattern = bytes(range(251))
    destination[:] = (pattern * (size // len(pattern) + 1))[:size]
    return image


def pixel_bytes(image):
    row_bytes = image.width() * image.depth() // 8
    data = bytes(image.constBits())
    stride = image.bytesPerLine()
    return b"".join(
        data[row * stride : row * stride + row_bytes] for row in range(image.height())
    )


class BandedImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_conversion_matches_the_whole_image_conversion(self):
        for size in (SMALL, LARGE):
            for source_format, target_format in (
                (ARGB32, PREMULTIPLIED),
                (ARGB32, GRAYSCALE),
                (RGB32, ARGB32),
                (PREMULTIPLIED, ARGB32),
            ):
                with self.subTest(
                    size=size, source=source_format, target=target_format
                ):
                    source = pattern_image(*size, source_format)
                    expected = source.convertToFormat(target_format)
                    actual = convert_to_format(source, target_format)
                    self.assertEqual(actual.format(), expected.format())
                    self.assertEqual(actual.size(), expected.size())
                    self.assertEqual(pixel_bytes(actual), pixel_bytes(expected))

    def test_copy_matches_the_source_and_is_independent_of_it(self):
        for size in (SMALL, LARGE):
            with self.subTest(size=size):
                source = pattern_image(*size)
                copied = copy_image(source)
                self.assertEqual(pixel_bytes(copied), pixel_bytes(source))
                source.setPixelColor(0, 0, QtGui.QColor(1, 2, 3, 4))
                self.assertNotEqual(pixel_bytes(copied), pixel_bytes(source))

    def test_region_copy_matches_the_whole_image_region_copy(self):
        source = pattern_image(1400, 900)
        for region in ((0, 0, 1400, 900), (13, 7, 1111, 701), (200, 100, 40, 30)):
            with self.subTest(region=region):
                expected = source.copy(*region)
                actual = copy_region(source, *region)
                self.assertEqual(actual.size(), expected.size())
                self.assertEqual(actual.format(), expected.format())
                self.assertEqual(pixel_bytes(actual), pixel_bytes(expected))

    def test_a_large_region_copy_is_banded(self):
        source = pattern_image(1400, 900)
        with recorded_image_operations() as operations:
            copy_region(source, 13, 7, 1111, 701)
        self.assertGreater(len(operations), 1)
        self.assertLessEqual(largest_operation(operations), BAND_PIXELS)

    def test_inversion_matches_the_whole_image_inversion_and_leaves_the_source(self):
        for size in (SMALL, LARGE):
            with self.subTest(size=size):
                source = pattern_image(*size)
                before = pixel_bytes(source)
                expected = source.copy()
                expected.invertPixels(QtGui.QImage.InvertMode.InvertRgb)
                actual = inverted_rgb(source)
                self.assertEqual(pixel_bytes(actual), pixel_bytes(expected))
                self.assertEqual(pixel_bytes(source), before)
                self.assertEqual(actual.format(), source.format())

    def test_darkening_matches_the_whole_image_darkening(self):
        paper = QtGui.QColor(220, 220, 220)
        for size in (SMALL, LARGE):
            with self.subTest(size=size):
                source = pattern_image(*size)
                expected = source.convertToFormat(PREMULTIPLIED)
                painter = QtGui.QPainter(expected)
                painter.setCompositionMode(
                    QtGui.QPainter.CompositionMode.CompositionMode_Darken
                )
                painter.fillRect(expected.rect(), paper)
                painter.end()
                actual = darkened_premultiplied(source, paper)
                self.assertEqual(actual.format(), PREMULTIPLIED)
                self.assertEqual(pixel_bytes(actual), pixel_bytes(expected))

    def test_image_metadata_survives_every_operation(self):
        source = pattern_image(*LARGE)
        source.setDotsPerMeterX(5670)
        source.setDotsPerMeterY(2835)
        source.setDevicePixelRatio(2.0)
        for name, result in (
            ("convert", convert_to_format(source, PREMULTIPLIED)),
            ("copy", copy_image(source)),
            ("invert", inverted_rgb(source)),
            ("darken", darkened_premultiplied(source, QtGui.QColor(220, 220, 220))),
        ):
            with self.subTest(operation=name):
                self.assertEqual(result.dotsPerMeterX(), 5670)
                self.assertEqual(result.dotsPerMeterY(), 2835)
                self.assertEqual(result.devicePixelRatio(), 2.0)

    def test_no_native_operation_exceeds_the_band_size_on_a_large_image(self):
        source = pattern_image(*LARGE)
        self.assertGreater(source.width() * source.height(), 2 * BAND_PIXELS)
        paper = QtGui.QColor(220, 220, 220)
        for name, operation in (
            ("convert", lambda: convert_to_format(source, PREMULTIPLIED)),
            ("copy", lambda: copy_image(source)),
            ("invert", lambda: inverted_rgb(source)),
            ("darken", lambda: darkened_premultiplied(source, paper)),
        ):
            with self.subTest(operation=name):
                with recorded_image_operations() as operations:
                    operation()
                self.assertTrue(operations)
                self.assertLessEqual(largest_operation(operations), BAND_PIXELS)

    def test_a_small_image_is_processed_by_single_whole_image_operations(self):
        source = pattern_image(*SMALL)
        with recorded_image_operations() as operations:
            convert_to_format(source, PREMULTIPLIED)
        self.assertEqual(operations, [("convertToFormat", SMALL[0] * SMALL[1])])

    def test_every_band_of_a_tall_narrow_image_stays_within_the_limit(self):
        source = pattern_image(3, 200000 // 3, ARGB32)
        with recorded_image_operations() as operations:
            result = convert_to_format(source, PREMULTIPLIED)
        self.assertLessEqual(largest_operation(operations), BAND_PIXELS)
        self.assertEqual(
            pixel_bytes(result), pixel_bytes(source.convertToFormat(PREMULTIPLIED))
        )

    def test_a_single_very_wide_row_is_still_processed(self):
        source = pattern_image(BAND_PIXELS + 50, 2, ARGB32)
        result = convert_to_format(source, PREMULTIPLIED)
        self.assertEqual(
            pixel_bytes(result), pixel_bytes(source.convertToFormat(PREMULTIPLIED))
        )

    def test_indexed_images_keep_their_color_table(self):
        source = QtGui.QImage(1000, 600, QtGui.QImage.Format.Format_Indexed8)
        source.setColorTable(
            [QtGui.qRgb(10 * index, 5 * index, index) for index in range(16)]
        )
        destination = source.bits()
        destination[:] = bytes(index % 16 for index in range(len(destination)))
        copied = copy_image(source)
        self.assertEqual(copied.format(), QtGui.QImage.Format.Format_Indexed8)
        self.assertEqual(copied.colorTable(), source.colorTable())
        self.assertEqual(pixel_bytes(copied), pixel_bytes(source))

    def test_a_null_image_gives_a_null_image(self):
        for operation in (
            lambda: convert_to_format(QtGui.QImage(), PREMULTIPLIED),
            lambda: copy_image(QtGui.QImage()),
            lambda: copy_region(QtGui.QImage(), 0, 0, 10, 10),
            lambda: inverted_rgb(QtGui.QImage()),
            lambda: darkened_premultiplied(QtGui.QImage(), QtGui.QColor(220, 220, 220)),
        ):
            self.assertTrue(operation().isNull())


if __name__ == "__main__":
    unittest.main()
