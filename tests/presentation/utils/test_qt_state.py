"""Persisted Qt window state is detached ASCII data, not a live QByteArray."""

import base64
import unittest
from PySide6.QtCore import QByteArray
from ost_visualizer.presentation.utils.qt_state import (
    decode_byte_array,
    encode_byte_array,
)


class QtStateTests(unittest.TestCase):
    def test_binary_state_roundtrips_and_does_not_retain_mutable_input(self):
        state = QByteArray(b"\x00\xff\x80window-state")
        encoded = encode_byte_array(state)
        state.clear()
        self.assertTrue(encoded.isascii())
        self.assertEqual(
            encoded, base64.b64encode(b"\x00\xff\x80window-state").decode("ascii")
        )
        self.assertEqual(bytes(decode_byte_array(encoded)), b"\x00\xff\x80window-state")

    def test_missing_empty_and_non_ascii_state_are_safe_empty_values(self):
        self.assertIsNone(encode_byte_array(QByteArray()))
        self.assertIsNone(encode_byte_array(None))
        for value in (None, "", 17, {}, "\u2603"):
            with self.subTest(value=value):
                self.assertTrue(decode_byte_array(value).isEmpty())
