import re
import tempfile
import unittest
import zlib
from dataclasses import fields
from pathlib import Path
from unittest import mock
from ost_visualizer.application.dtos.annotation_caption_dto import (
    AnnotationCaptionSettingsDto,
)
from ost_visualizer.application.dtos.page_export_data_dto import PageExportData
from ost_visualizer.application.services.annotation_caption_resolver import (
    AnnotationCaptionResolver,
)
from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.elevation_callout import (
    ElevationCallout,
    ElevationCalloutSettings,
)
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.domain.services.elevation_callout_service import (
    resolve_elevation_callout,
)
from ost_visualizer.domain.services.takeoff_service_impl import TakeoffDomainService
from ost_visualizer.domain.services.uom_service_impl import UOMDomainService
from ost_visualizer.infrastructure.persistence.repositories.json_config_repository import (
    JsonConfigRepository,
)
from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer
from ost_visualizer.presentation.visualization.exporters.pdf_exporter import PDFExporter
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)

_EXPECTED_PDF_CALLOUT_LINES = ["F9", "10' - 0\"", "8' - 0\"", "5.14 CY"]


def _outer_ring(outer_ring=None):
    if outer_ring is None:
        outer_ring = (
            (10.0, 20.0),
            (50.0, 20.0),
            (50.0, 60.0),
            (10.0, 60.0),
        )
    return tuple(outer_ring)


def _area_condition(**overrides):
    values = {
        "uid": "condition-1",
        "name": "F9 @T 10' 0\"",
        "condition_type": Condition.TYPE_AREA,
        "thickness": 24.0,
        "z_value": 120.0,
        "is_top": True,
    }
    values.update(overrides)
    return Condition(**values)


def _area_takeoff(**overrides):
    values = {
        "uid": "takeoff-1",
        "condition_uid": "condition-1",
        "page_uid": "page-1",
        "area_uid": "area-1",
        "position": [0.0, 0.0, 100.0, 0.0, 100.0, 100.0, 0.0, 100.0],
    }
    values.update(overrides)
    return Takeoff(**values)


class _CapturingPdfWriter:
    def __init__(self):
        self.pages = []

    def merge_pages_with_annotations(self, pages, _output_path):
        self.pages = list(pages)
        return True

    def get_last_error(self):
        return ""
