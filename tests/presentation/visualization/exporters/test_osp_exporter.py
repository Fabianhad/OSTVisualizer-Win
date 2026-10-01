import tempfile
import unittest
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from typing import Optional
from unittest.mock import patch
from ost_visualizer.application.dtos.export_dto import (
    ExportErrorCode,
    ExportProgressCallback,
    ExportRequestDto,
    ExportResultDto,
)
from ost_visualizer.domain.dtos.raw_bid_data_dto import RawBidData
from ost_visualizer.presentation.visualization.exporters import osp_exporter
from ost_visualizer.presentation.visualization.exporters.osp_exporter import OspExporter
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.export_dto import (
    ExportProgressCallback,
    ExportResultDto,
)
from ost_visualizer.presentation.visualization.exporters import (
    osp_exporter as osp_exporter_module,
)


class OspExporterProgressTests(unittest.TestCase):
    def _unused_ost_exporter_factory(self, _uom_service):
        self.fail("OST exporter should not be constructed")

    def _make_osp_exporter(self, ost_exporter_factory=None):
        return OspExporter(
            SimpleNamespace(),
            "1.0",
            ost_exporter_factory or self._unused_ost_exporter_factory,
        )

    def test_collect_images_reports_each_included_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.pdf"
            second = Path(tmp) / "second.tif"
            ignored = Path(tmp) / "ignored.jpg"
            first.write_bytes(b"pdf")
            second.write_bytes(b"tif")
            ignored.write_bytes(b"jpg")
            raw_data = RawBidData(
                bid_tables={
                    "BidPages": [
                        {"ImagePath": str(first), "OverlayImagePath": ""},
                        {"ImagePath": str(ignored), "OverlayImagePath": str(second)},
                        {"ImagePath": str(first), "OverlayImagePath": ""},
                    ]
                }
            )
            exporter = self._make_osp_exporter()
            (
                _package_data,
                image_sources,
                missing,
            ) = exporter._prepare_package_data(raw_data)
            self.assertEqual(missing, [])
            source_files = []
            archive_names = []
            progress = []
            exporter._collect_images(
                image_sources,
                source_files,
                archive_names,
                lambda current, total, description: progress.append(
                    (current, total, description)
                ),
            )
        self.assertEqual(source_files, [str(first.resolve()), str(second.resolve())])
        self.assertEqual(
            archive_names,
            ["TempImages!.tmp\\first.pdf", "TempImages!.tmp\\second.tif"],
        )
        self.assertEqual(
            progress,
            [(1, 2, "Collecting first.pdf"), (2, 2, "Collecting second.tif")],
        )

    def test_collect_images_without_images_reports_nothing_and_appends_nothing(self):
        source_files = ["existing.ost"]
        archive_names = ["Bid.ost"]
        progress = []
        self._make_osp_exporter()._collect_images(
            {},
            source_files,
            archive_names,
            lambda current, total, description: progress.append(
                (current, total, description)
            ),
        )
        self.assertEqual(source_files, ["existing.ost"])
        self.assertEqual(archive_names, ["Bid.ost"])
        self.assertEqual(progress, [])

    def test_prepare_package_data_flattens_distinct_same_filename_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            first_dir = Path(tmp) / "first"
            second_dir = Path(tmp) / "second"
            first_dir.mkdir()
            second_dir.mkdir()
            first = first_dir / "sheet.pdf"
            second = second_dir / "sheet.pdf"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            raw_data = RawBidData(
                bid_row={"UID": "1", "JobName": "Bid"},
                bid_tables={
                    "BidPages": [
                        {"UID": "10", "BidUID": "1", "ImagePath": str(first)},
                        {"UID": "11", "BidUID": "1", "ImagePath": str(second)},
                    ]
                },
            )
            exporter = self._make_osp_exporter()
            (
                package_data,
                image_sources,
                missing,
            ) = exporter._prepare_package_data(raw_data)
        page_paths = [row["ImagePath"] for row in package_data.bid_tables["BidPages"]]
        self.assertEqual(missing, [])
        self.assertEqual(len(image_sources), 2)
        self.assertEqual(
            set(image_sources.values()), {str(first.resolve()), str(second.resolve())}
        )
        self.assertEqual(len({path.casefold() for path in image_sources}), 2)
        self.assertTrue(
            all(
                path.startswith("TempImages!.tmp\\") and path.count("\\") == 1
                for path in image_sources
            )
        )
        self.assertEqual(len(set(page_paths)), 2)
        self.assertEqual(set(page_paths), set(image_sources))
        # Each Page row must point at the member holding its own drawing file.
        self.assertTrue(page_paths[0].startswith("TempImages!.tmp\\10_"))
        self.assertTrue(page_paths[1].startswith("TempImages!.tmp\\11_"))
        self.assertTrue(all(path.endswith("_sheet.pdf") for path in page_paths))
        self.assertEqual(image_sources[page_paths[0]], str(first.resolve()))
        self.assertEqual(image_sources[page_paths[1]], str(second.resolve()))
        # The caller's rows keep the original database paths.
        self.assertEqual(
            [row["ImagePath"] for row in raw_data.bid_tables["BidPages"]],
            [str(first), str(second)],
        )

    def test_prepare_package_data_preserves_database_paths_for_unique_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "A0.01.pdf"
            image.write_bytes(b"pdf")
            raw_data = RawBidData(
                bid_row={"UID": "1", "JobName": "Ignored"},
                bid_tables={
                    "BidPages": [{"UID": "10", "BidUID": "1", "ImagePath": str(image)}]
                },
            )
            exporter = self._make_osp_exporter()
            (
                package_data,
                image_sources,
                missing,
            ) = exporter._prepare_package_data(raw_data)
        self.assertEqual(missing, [])
        self.assertEqual(
            image_sources, {"TempImages!.tmp\\A0.01.pdf": str(image.resolve())}
        )
        self.assertEqual(
            package_data.bid_tables["BidPages"][0]["ImagePath"],
            str(image),
        )
        self.assertFalse(
            package_data.bid_tables["BidPages"][0]["ImagePath"].startswith(
                "TempImages!.tmp"
            )
        )

    def test_prepare_package_data_maps_case_insensitive_filename_collisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            first_dir = Path(tmp) / "first"
            second_dir = Path(tmp) / "second"
            first_dir.mkdir()
            second_dir.mkdir()
            first = first_dir / "sheet.pdf"
            second = second_dir / "SHEET.PDF"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            raw_data = RawBidData(
                bid_row={"UID": "1", "JobName": "Bid"},
                bid_tables={
                    "BidPages": [
                        {"UID": "10", "BidUID": "1", "ImagePath": str(first)},
                        {"UID": "11", "BidUID": "1", "ImagePath": str(second)},
                    ]
                },
            )
            exporter = self._make_osp_exporter()
            (
                package_data,
                image_sources,
                missing,
            ) = exporter._prepare_package_data(raw_data)
        page_paths = [row["ImagePath"] for row in package_data.bid_tables["BidPages"]]
        self.assertEqual(missing, [])
        self.assertEqual(len(image_sources), 2)
        self.assertEqual(
            set(image_sources.values()), {str(first.resolve()), str(second.resolve())}
        )
        self.assertEqual(len({path.casefold() for path in image_sources}), 2)
        self.assertTrue(all(path.count("\\") == 1 for path in image_sources))
        self.assertEqual(len(set(page_paths)), 2)
        self.assertEqual(set(page_paths), set(image_sources))
        self.assertEqual(image_sources[page_paths[0]], str(first.resolve()))
        self.assertEqual(image_sources[page_paths[1]], str(second.resolve()))
        self.assertTrue(page_paths[0].endswith("_sheet.pdf"))
        self.assertTrue(page_paths[1].endswith("_SHEET.PDF"))

    def test_prepare_package_data_avoids_generated_and_direct_name_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first" / "sheet.pdf"
            second = root / "second" / "sheet.pdf"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            exporter = self._make_osp_exporter()
            generated_member = exporter._collision_package_image_member_path(
                str(first.resolve()).casefold(),
                first.name,
                "10",
            )
            third = root / "third" / PureWindowsPath(generated_member).name
            third.parent.mkdir()
            third.write_bytes(b"third")
            raw_data = RawBidData(
                bid_tables={
                    "BidPages": [
                        {"UID": "10", "ImagePath": str(first)},
                        {"UID": "11", "ImagePath": str(second)},
                        {"UID": "12", "ImagePath": str(third)},
                    ]
                }
            )
            package_data, image_sources, missing = exporter._prepare_package_data(
                raw_data
            )
            repeated_data, repeated_sources, repeated_missing = (
                exporter._prepare_package_data(raw_data)
            )
        page_paths = [row["ImagePath"] for row in package_data.bid_tables["BidPages"]]
        self.assertEqual(missing, [])
        self.assertEqual(len(image_sources), 3)
        self.assertEqual(len({name.casefold() for name in image_sources}), 3)
        self.assertEqual(
            set(image_sources.values()),
            {str(first.resolve()), str(second.resolve()), str(third.resolve())},
        )
        self.assertEqual(set(page_paths), set(image_sources))
        self.assertTrue(all(name.count("\\") == 1 for name in image_sources))
        # The generated member name for the first image wins; the third image whose
        # own file name equals it is renamed with a numeric suffix.
        self.assertEqual(page_paths[0], generated_member)
        self.assertEqual(
            page_paths[2],
            generated_member[: -len(".pdf")] + "_2.pdf",
        )
        self.assertEqual(image_sources[page_paths[0]], str(first.resolve()))
        self.assertEqual(image_sources[page_paths[1]], str(second.resolve()))
        self.assertEqual(image_sources[page_paths[2]], str(third.resolve()))
        self.assertEqual(repeated_missing, missing)
        self.assertEqual(repeated_sources, image_sources)
        self.assertEqual(
            [row["ImagePath"] for row in repeated_data.bid_tables["BidPages"]],
            page_paths,
        )

    def test_osp_export_writes_original_app_compatible_flat_image_member(self):
        class FakeOstExporter:
            def __init__(self, _uom_service):
                pass

            def export(self, _raw_data, output_path, on_progress=None):
                Path(output_path).write_text("ost", encoding="utf-8")
                return ExportResultDto(success=True, format_name="OST")

        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "sheet.pdf"
            image.write_bytes(b"pdf")
            output = Path(tmp) / "out.osp"
            raw_data = RawBidData(
                bid_tables={"BidPages": [{"UID": "10", "ImagePath": str(image)}]}
            )
            exporter = self._make_osp_exporter(FakeOstExporter)
            result = exporter.export(raw_data, str(output))
            archive_names = list(osp_exporter.ost_cab.list_cab(str(output)))
        self.assertTrue(result.success, result.error_message)
        self.assertEqual(
            archive_names, ["Bid.ost", "BidTrans.xml", "TempImages!.tmp\\sheet.pdf"]
        )
        self.assertFalse(
            any(
                name.startswith("TempImages!.tmp\\") and name.count("\\") > 1
                for name in archive_names
            )
        )

    def test_prepare_package_data_reports_missing_drawing_files(self):
        raw_data = RawBidData(
            bid_row={"UID": "1", "JobName": "Bid"},
            bid_tables={
                "BidPages": [
                    {
                        "UID": "10",
                        "BidUID": "1",
                        "ImagePath": r"C:\missing\sheet.pdf",
                    }
                ]
            },
        )
        exporter = self._make_osp_exporter()
        (
            package_data,
            image_sources,
            missing,
        ) = exporter._prepare_package_data(raw_data)
        self.assertEqual(image_sources, {})
        self.assertEqual(missing, [r"C:\missing\sheet.pdf"])
        self.assertEqual(
            package_data.bid_tables["BidPages"][0]["ImagePath"],
            r"C:\missing\sheet.pdf",
        )

    def test_osp_export_with_missing_drawing_files_fails_before_building_ost(self):
        raw_data = RawBidData(
            bid_tables={
                "BidPages": [
                    {"UID": "10", "ImagePath": r"C:\missing\sheet.pdf"},
                    {"UID": "11", "OverlayImagePath": r"C:\missing\overlay.tif"},
                ]
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.osp"
            with patch.object(osp_exporter.ost_cab, "create_cab_with_names") as cab:
                result = self._make_osp_exporter().export(raw_data, str(output))
            self.assertFalse(output.exists())
            self.assertEqual(os.listdir(tmp), [])
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, ExportErrorCode.WRITE_FAILED)
        self.assertEqual(
            result.error_message,
            "Cannot export OSP because referenced drawing files are missing: "
            r"C:\missing\sheet.pdf; C:\missing\overlay.tif",
        )
        cab.assert_not_called()

    def test_osp_export_reports_image_progress_before_packaging(self):
        class FakeOstExporter:
            def __init__(self, _uom_service):
                pass

            def export(
                self,
                _raw_data,
                output_path,
                on_progress: Optional[ExportProgressCallback] = None,
            ):
                Path(output_path).write_text("ost", encoding="utf-8")
                return ExportResultDto(success=True, format_name="OST")

        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "sheet.pdf"
            output = Path(tmp) / "out.osp"
            image.write_bytes(b"pdf")
            raw_data = RawBidData(
                bid_tables={
                    "BidPages": [{"ImagePath": str(image), "OverlayImagePath": ""}]
                }
            )
            cab_calls = []
            progress = []
            original_create_cab = osp_exporter.ost_cab.create_cab_with_names
            try:
                osp_exporter.ost_cab.create_cab_with_names = (
                    lambda source_files, archive_names, output_file: cab_calls.append(
                        (list(source_files), list(archive_names), output_file)
                    )
                    or True
                )
                exporter = self._make_osp_exporter(
                    lambda uom_service: FakeOstExporter(uom_service)
                )
                result = exporter.export(
                    raw_data,
                    str(output),
                    "Bid",
                    on_progress=lambda current, total, description: progress.append(
                        (current, total, description)
                    ),
                )
            finally:
                osp_exporter.ost_cab.create_cab_with_names = original_create_cab
        self.assertTrue(result.success)
        self.assertEqual(
            progress,
            [
                (1, 4, "Building OST"),
                (2, 4, "Writing metadata"),
                (3, 4, "Collecting images"),
                (1, 1, "Collecting sheet.pdf"),
                (4, 4, "Packaging archive"),
            ],
        )
        self.assertEqual(len(cab_calls), 1)
        self.assertEqual(
            cab_calls[0][1], ["Bid.ost", "BidTrans.xml", "TempImages!.tmp\\sheet.pdf"]
        )
        self.assertEqual(cab_calls[0][0][2], str(image.resolve()))

    def test_osp_export_preserves_database_image_paths_in_embedded_ost(self):
        class FakeOstExporter:
            captured_rows = []

            def __init__(self, _uom_service):
                pass

            def export(
                self,
                raw_data,
                output_path,
                on_progress: Optional[ExportProgressCallback] = None,
            ):
                self.captured_rows = [
                    dict(row) for row in raw_data.bid_tables.get("BidPages", [])
                ]
                Path(output_path).write_text("ost", encoding="utf-8")
                return ExportResultDto(success=True, format_name="OST")

        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "A0.02.pdf"
            output = Path(tmp) / "out.osp"
            image.write_bytes(b"pdf")
            raw_data = RawBidData(
                bid_tables={
                    "BidPages": [{"ImagePath": str(image), "OverlayImagePath": ""}]
                }
            )
            archive_name_calls = []
            original_create_cab = osp_exporter.ost_cab.create_cab_with_names
            try:
                osp_exporter.ost_cab.create_cab_with_names = (
                    lambda _source_files, archive_names, _output_file: (
                        archive_name_calls.append(list(archive_names)) or True
                    )
                )
                fake_exporter = FakeOstExporter(SimpleNamespace())
                exporter = self._make_osp_exporter(
                    lambda _uom_service: fake_exporter,
                )
                result = exporter.export(
                    raw_data,
                    str(output),
                    "26-053 8201 Metcalf Overland Park, KS",
                )
            finally:
                osp_exporter.ost_cab.create_cab_with_names = original_create_cab
        self.assertTrue(result.success)
        self.assertEqual(
            fake_exporter.captured_rows,
            [{"ImagePath": str(image), "OverlayImagePath": ""}],
        )
        self.assertEqual(
            archive_name_calls,
            [
                [
                    "26-053 8201 Metcalf Overland Park, KS.ost",
                    "BidTrans.xml",
                    "TempImages!.tmp\\A0.02.pdf",
                ]
            ],
        )

    def test_osp_export_failure_preserves_existing_destination(self):
        class FakeOstExporter:
            def export(self, _raw_data, output_path):
                Path(output_path).write_text("ost", encoding="utf-8")
                return ExportResultDto(success=True, format_name="OST")

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "existing.osp"
            output.write_bytes(b"existing archive")
            cab_outputs = []

            def fail_after_partial_write(_source_files, _archive_names, temp_output):
                cab_outputs.append(Path(temp_output))
                Path(temp_output).write_bytes(b"partial archive")
                return False

            with patch.object(
                osp_exporter.ost_cab,
                "create_cab_with_names",
                side_effect=fail_after_partial_write,
            ):
                result = self._make_osp_exporter(
                    lambda _uom_service: FakeOstExporter()
                ).export(RawBidData(), str(output))
            self.assertFalse(result.success)
            self.assertEqual(result.error_code, ExportErrorCode.WRITE_FAILED)
            self.assertEqual(result.error_message, "Failed to create CAB archive")
            self.assertEqual(output.read_bytes(), b"existing archive")
            self.assertEqual(len(cab_outputs), 1)
            self.assertNotEqual(cab_outputs[0], output)
            self.assertFalse(cab_outputs[0].exists())
            self.assertEqual(os.listdir(tmp), ["existing.osp"])

    def test_osp_export_success_replaces_existing_destination_without_leftovers(self):
        class FakeOstExporter:
            def export(self, _raw_data, output_path):
                Path(output_path).write_text("ost", encoding="utf-8")
                return ExportResultDto(success=True, format_name="OST")

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "existing.osp"
            output.write_bytes(b"existing archive")
            cab_outputs = []

            def write_new_archive(_source_files, _archive_names, temp_output):
                cab_outputs.append(Path(temp_output))
                Path(temp_output).write_bytes(b"new archive")
                return True

            with patch.object(
                osp_exporter.ost_cab,
                "create_cab_with_names",
                side_effect=write_new_archive,
            ):
                result = self._make_osp_exporter(
                    lambda _uom_service: FakeOstExporter()
                ).export(RawBidData(), str(output))
            self.assertTrue(result.success, result.error_message)
            self.assertEqual(output.read_bytes(), b"new archive")
            self.assertEqual(len(cab_outputs), 1)
            self.assertNotEqual(cab_outputs[0], output)
            self.assertEqual(os.listdir(tmp), ["existing.osp"])


class PresentationImportExportWorkflowTests(unittest.TestCase):
    def test_osp_export_keeps_named_view_hotlink_tables_and_distinct_same_filename_images(
        self,
    ):
        class CapturingOstExporter:
            captured_raw_data = None

            def __init__(self, _uom_service):
                pass

            def export(
                self,
                raw_data,
                output_path,
                on_progress: Optional[ExportProgressCallback] = None,
            ):
                CapturingOstExporter.captured_raw_data = raw_data
                Path(output_path).write_text("<XML_ROOT />", encoding="utf-8")
                return ExportResultDto(success=True, format_name="OST")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            first_dir = tmp_path / "first"
            second_dir = tmp_path / "second"
            first_dir.mkdir()
            second_dir.mkdir()
            first = first_dir / "sheet.pdf"
            second = second_dir / "sheet.pdf"
            first.write_bytes(b"%PDF-1.4 first")
            second.write_bytes(b"%PDF-1.4 second")
            raw_data = RawBidData(
                bid_row={"UID": "1", "JobName": "Corpus Workflow"},
                bid_tables={
                    "BidPages": [
                        {"UID": "10", "BidUID": "1", "ImagePath": str(first)},
                        {"UID": "11", "BidUID": "1", "ImagePath": str(second)},
                    ],
                    "BidNamedViews": [
                        {
                            "UID": "201",
                            "BidUID": "1",
                            "BidPageUID": "10",
                            "Name": "View A",
                        }
                    ],
                    "BidHotLinks": [
                        {"UID": "301", "BidUID": "1", "BidPageViewUID": "201"}
                    ],
                },
            )
            cab_calls = []
            original_create_cab = osp_exporter_module.ost_cab.create_cab_with_names
            try:
                osp_exporter_module.ost_cab.create_cab_with_names = (
                    lambda source_files, archive_names, output_file: cab_calls.append(
                        (list(source_files), list(archive_names), output_file)
                    )
                    or True
                )
                exporter = OspExporter(
                    SimpleNamespace(),
                    "1.0",
                    lambda uom_service: CapturingOstExporter(uom_service),
                )
                result = exporter.export(raw_data, str(tmp_path / "out.osp"), "Bid")
            finally:
                osp_exporter_module.ost_cab.create_cab_with_names = original_create_cab
        self.assertTrue(result.success)
        captured = CapturingOstExporter.captured_raw_data
        self.assertIsNotNone(captured)
        page_paths = [row["ImagePath"] for row in captured.bid_tables["BidPages"]]
        self.assertEqual(len(set(page_paths)), 2)
        self.assertTrue(
            all(
                path.startswith("TempImages!.tmp\\") and path.count("\\") == 1
                for path in page_paths
            )
        )
        self.assertEqual(
            captured.bid_tables["BidNamedViews"],
            [{"UID": "201", "BidUID": "1", "BidPageUID": "10", "Name": "View A"}],
        )
        self.assertEqual(
            captured.bid_tables["BidHotLinks"],
            [{"UID": "301", "BidUID": "1", "BidPageViewUID": "201"}],
        )
        self.assertEqual(len(cab_calls), 1)
        image_archive_names = [
            name for name in cab_calls[0][1] if name.startswith("TempImages!.tmp\\")
        ]
        self.assertEqual(len(image_archive_names), 2)
        self.assertEqual(len(set(image_archive_names)), 2)
        self.assertCountEqual(image_archive_names, page_paths)
        archive_sources = dict(zip(cab_calls[0][1], cab_calls[0][0]))
        self.assertEqual(archive_sources[page_paths[0]], str(first.resolve()))
        self.assertEqual(archive_sources[page_paths[1]], str(second.resolve()))
        self.assertEqual(
            [row["UID"] for row in captured.bid_tables["BidPages"]], ["10", "11"]
        )
        self.assertEqual(captured.bid_row, {"UID": "1", "JobName": "Corpus Workflow"})
