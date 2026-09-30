import base64
import tempfile
import unittest
from pathlib import Path
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.services.page_image_plane_transform import (
    PAGE_PLANE_FLOOR_OFFSET,
    resolve_page_floor_elevations,
)
from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer
from ost_visualizer.presentation.visualization.renderers.threejs.threejs_renderer import (
    _build_multi_page_data,
    visualize_with_threejs,
)
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)
from tests.presentation.visualization.renderers.threejs.export_support import (
    _TakeoffService as _export_support__TakeoffService,
    _build_pages_without_takeoffs as _export_support__build_pages_without_takeoffs,
    _decode_pdf_document as _export_support__decode_pdf_document,
    _page_template as _export_support__page_template,
    _pdf_page_sizes as _export_support__pdf_page_sizes,
    _write_minimal_pdf as _export_support__write_minimal_pdf,
)


class ThreejsExportLayerTests(unittest.TestCase):
    def test_multi_page_renderer_data_embeds_only_selected_pdf_page(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "pages.pdf"
            _export_support__write_minimal_pdf(
                pdf_path, [(612, 792), (300, 400), (500, 600)]
            )
            source_size = pdf_path.stat().st_size
            page_entries, pdf_documents, takeoffs_2d = (
                _export_support__build_pages_without_takeoffs(
                    [_export_support__page_template(pdf_path, "page-2", 1)],
                    page_floor_elevations={"page-2": 4.0},
                )
            )
        self.assertEqual(len(pdf_documents), 1)
        embedded_pdf = _export_support__decode_pdf_document(pdf_documents[0])
        self.assertLess(len(embedded_pdf), source_size)
        self.assertEqual(
            _export_support__pdf_page_sizes(embedded_pdf), [[300.0, 400.0, 0.0, 0.0]]
        )
        self.assertEqual(page_entries[0]["pdf_document_uid"], "pdf-1")
        self.assertEqual(page_entries[0]["pdf_page_index"], 1)
        self.assertEqual(page_entries[0]["plane_x"], -0.5)
        self.assertAlmostEqual(
            page_entries[0]["plane_y"], 4.0 - PAGE_PLANE_FLOOR_OFFSET
        )
        self.assertEqual(page_entries[0]["plane_z"], -0.5)
        self.assertTrue(page_entries[0]["plane_flip_u"])
        self.assertTrue(page_entries[0]["plane_flip_v"])
        self.assertNotIn("image_visible", page_entries[0])
        self.assertEqual(takeoffs_2d, [])

    def test_multi_page_plane_elevations_are_owned_by_each_page_uid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "pages.pdf"
            _export_support__write_minimal_pdf(pdf_path, [(612, 792), (300, 400)])
            page_entries, _pdf_documents, _takeoffs_2d = (
                _export_support__build_pages_without_takeoffs(
                    [
                        _export_support__page_template(pdf_path, "page-b", 1),
                        _export_support__page_template(pdf_path, "page-a", 0),
                    ],
                    page_floor_elevations={"page-a": 10.0, "page-b": 25.0},
                )
            )
        elevations = {page["uid"]: page["plane_y"] for page in page_entries}
        self.assertEqual(
            elevations,
            {
                "page-a": 10.0 - PAGE_PLANE_FLOOR_OFFSET,
                "page-b": 25.0 - PAGE_PLANE_FLOOR_OFFSET,
            },
        )

    def test_multi_page_entry_without_geometry_has_no_origin_plane(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "pages.pdf"
            _export_support__write_minimal_pdf(pdf_path, [(612, 792)])
            page_entries, _pdf_documents, _takeoffs_2d = (
                _export_support__build_pages_without_takeoffs(
                    [_export_support__page_template(pdf_path, "page-a", 0)],
                    page_floor_elevations={},
                )
            )
        self.assertNotIn("plane_y", page_entries[0])

    def test_multi_page_renderer_data_embeds_only_selected_pages_from_source_pdf(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "pages.pdf"
            _export_support__write_minimal_pdf(
                pdf_path, [(612, 792), (300, 400), (500, 600)]
            )
            page_entries, pdf_documents, takeoffs_2d = (
                _export_support__build_pages_without_takeoffs(
                    [
                        _export_support__page_template(pdf_path, "page-1", 0),
                        _export_support__page_template(pdf_path, "page-3", 2),
                    ]
                )
            )
        self.assertEqual(len(pdf_documents), 2)
        self.assertEqual(
            [
                _export_support__pdf_page_sizes(
                    _export_support__decode_pdf_document(document)
                )
                for document in pdf_documents
            ],
            [
                [[612.0, 792.0, 0.0, 0.0]],
                [[500.0, 600.0, 0.0, 0.0]],
            ],
        )
        self.assertEqual(
            [page["pdf_document_uid"] for page in page_entries],
            ["pdf-1", "pdf-2"],
        )
        self.assertEqual([page["pdf_page_index"] for page in page_entries], [0, 2])
        self.assertEqual(takeoffs_2d, [])

    def test_multi_page_renderer_data_deduplicates_same_source_pdf_page(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "pages.pdf"
            _export_support__write_minimal_pdf(pdf_path, [(612, 792), (300, 400)])
            page_entries, pdf_documents, _takeoffs_2d = (
                _export_support__build_pages_without_takeoffs(
                    [
                        _export_support__page_template(pdf_path, "page-2-a", 1),
                        _export_support__page_template(pdf_path, "page-2-b", 1),
                    ]
                )
            )
        self.assertEqual(len(pdf_documents), 1)
        self.assertEqual(
            [page["pdf_document_uid"] for page in page_entries],
            ["pdf-1", "pdf-1"],
        )
        self.assertEqual(
            _export_support__pdf_page_sizes(
                _export_support__decode_pdf_document(pdf_documents[0])
            ),
            [[300.0, 400.0, 0.0, 0.0]],
        )

    def test_multi_page_renderer_data_keeps_separate_single_page_pdf_assets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            first_pdf_path = Path(tmpdir) / "first.pdf"
            second_pdf_path = Path(tmpdir) / "second.pdf"
            _export_support__write_minimal_pdf(first_pdf_path, [(612, 792)])
            _export_support__write_minimal_pdf(second_pdf_path, [(300, 400)])
            page_entries, pdf_documents, _takeoffs_2d = (
                _export_support__build_pages_without_takeoffs(
                    [
                        _export_support__page_template(first_pdf_path, "page-1", 0),
                        _export_support__page_template(second_pdf_path, "page-2", 0),
                    ]
                )
            )
        self.assertEqual(len(pdf_documents), 2)
        self.assertEqual(
            [
                _export_support__pdf_page_sizes(
                    _export_support__decode_pdf_document(document)
                )
                for document in pdf_documents
            ],
            [
                [[612.0, 792.0, 0.0, 0.0]],
                [[300.0, 400.0, 0.0, 0.0]],
            ],
        )
        self.assertEqual([page["pdf_page_index"] for page in page_entries], [0, 0])
