import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.application.render_quality import (
    CONSTRAINED_RENDER_SCALE_FLOOR,
    RASTER_NATIVE_RENDER_SCALE,
)
from ost_visualizer.application.services.page_visualization_metadata_service import (
    PageVisualizationMetadataService,
)
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.services.page_image_plane_transform import (
    PAGE_PLANE_FLOOR_OFFSET,
    native_page_plane_transform,
    threejs_page_plane_transform,
)
from ost_visualizer.presentation.visualization.native_page_plane import (
    NATIVE_PLAN_TEXTURE_MAX_DIMENSION,
    NativePageImagePlaneProvider,
    native_plan_texture_render_scale,
    qimage_to_rgba_bytes,
)
from PySide6 import QtGui


class FakeProjectData:
    def __init__(self, page, *, selected_page_uids=None):
        pages = page if isinstance(page, list) else [page]
        self.pages = {item.uid: item for item in pages}
        self.selected_page_uids = list(
            selected_page_uids if selected_page_uids is not None else self.pages.keys()
        )

    def get_page(self, page_uid):
        return self.pages.get(page_uid)

    def get_selected_page_uids(self):
        return list(self.selected_page_uids)

    def get_last_selected_page_uid(self):
        return self.selected_page_uids[0] if self.selected_page_uids else None

    def get_image_layer_uid(self):
        return "image"


class FakePageCache:
    def __init__(self, image):
        self.image = image
        self.calls = []

    def get_page(self, file_path, page_index=0, scale=1.0, rotation=0):
        self.calls.append((file_path, page_index, scale, rotation))
        return self.image
