import math
import unittest
from types import SimpleNamespace
from ost_visualizer.application.dtos.render_result_dto import RenderResult
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGraphicsScene


def _raw_char(text, left, right, bottom, top):
    return SimpleNamespace(
        text=text,
        left=left,
        right=right,
        bottom=bottom,
        top=top,
    )


def _raw_run(text, left, right, bottom, top, chars):
    return SimpleNamespace(
        text=text,
        left=left,
        right=right,
        bottom=bottom,
        top=top,
        chars=chars,
    )


class FakeRenderingService:
    def __init__(self):
        self.cancelled = []
        self.requests = []

    def extract_pdf_text_async(self, file_path, page_index, callback, priority=2):
        self.requests.append((file_path, page_index, callback, priority))
        return "text-request-1"

    def cancel_request(self, request_id):
        self.cancelled.append(request_id)


class FakeTrackingViewport:
    def __init__(self):
        self.tracking = []
        self.updates = 0
        self.cursor = None

    def setMouseTracking(self, enabled):
        self.tracking.append(enabled)

    def update(self):
        self.updates += 1

    def setCursor(self, cursor):
        self.cursor = cursor


def _page_info(
    *,
    pdf_width=200.0,
    pdf_height=100.0,
    media_width=200.0,
    media_height=100.0,
    crop_width=0.0,
    crop_height=0.0,
    rotation=0,
):
    return {
        "pdf_width": pdf_width,
        "pdf_height": pdf_height,
        "media_width_pts": media_width,
        "media_height_pts": media_height,
        "crop_width_pts": crop_width,
        "crop_height_pts": crop_height,
        "intrinsic_rotation": rotation,
    }
