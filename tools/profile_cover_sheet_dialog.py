import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from PySide6 import QtWidgets

from ost_visualizer.domain.entities.cover_sheet import CoverSheetData, CoverSheetPage
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.presentation.dialogs.cover_sheet.dialog import CoverSheetDialog


class _IconProvider:
    @staticmethod
    def set_window_icon(_window) -> None:
        return None


def _build_data(page_count: int, paths: list[str]) -> CoverSheetData:
    return CoverSheetData(
        bid_uid="profile",
        job_status_uid="",
        job_name="Cover Sheet profile",
        estimator_uid="",
        notes="",
        bid_date="2026 01 01 08 00 00",
        bid_no="1",
        job_id="",
        pages_without_folder=[
            CoverSheetPage(
                uid=f"page-{index}",
                sheet_no=f"{index + 1:05d}",
                name=f"Page {index + 1}",
                width=42.0,
                height=30.0,
                scale_factor1=0.125,
                scale_factor2=12.0,
                image_path=paths[index],
                overlay_image_path="",
                index=1,
                show_mode=0,
                multi_page_count=1 if paths[index] else 0,
            )
            for index in range(page_count)
        ],
    )


def _page_count(data: CoverSheetData) -> int:
    def folder_count(folder) -> int:
        return len(folder.pages) + sum(
            folder_count(child) for child in folder.subfolders.values()
        )

    return len(data.pages_without_folder) + sum(
        folder_count(folder) for folder in data.folders.values()
    )


def _measure(
    data: CoverSheetData,
    page_sizes,
    *,
    data_load_seconds: float = 0.0,
) -> dict[str, float | int]:
    provider_calls = 0

    def counted_page_sizes(path: str):
        nonlocal provider_calls
        provider_calls += 1
        return page_sizes(path)

    started = time.perf_counter()
    dialog = CoverSheetDialog(
        _IconProvider(),
        None,
        data,
        pdf_page_sizes_fn=counted_page_sizes,
    )
    construction_seconds = time.perf_counter() - started
    try:
        started = time.perf_counter()
        dialog.show()
        QtWidgets.QApplication.processEvents()
        layout_seconds = time.perf_counter() - started
        return {
            "rows": _page_count(data),
            "data_load_seconds": data_load_seconds,
            "construction_seconds": construction_seconds,
            "layout_seconds": layout_seconds,
            "total_seconds": (
                data_load_seconds + construction_seconds + layout_seconds
            ),
            "provider_calls": provider_calls,
            "qwidgets": len(dialog.findChildren(QtWidgets.QWidget)),
            "qcomboboxes": len(dialog.findChildren(QtWidgets.QComboBox)),
        }
    finally:
        dialog.reject()
        dialog.deleteLater()
        QtWidgets.QApplication.processEvents()


def _profile_synthetic(
    page_count: int, metadata_delay_ms: float
) -> dict[str, float | int]:
    with tempfile.TemporaryDirectory() as temp_dir:
        paths = []
        if metadata_delay_ms:
            for index in range(page_count):
                path = Path(temp_dir) / f"page-{index}.pdf"
                path.write_bytes(b"%PDF-1.4\n")
                paths.append(str(path))
        else:
            paths = [""] * page_count

        def _page_sizes(_path: str):
            time.sleep(metadata_delay_ms / 1000.0)
            return [(42.0, 30.0, "Page 1")]

        return _measure(_build_data(page_count, paths), _page_sizes)


def _profile_mdb(path: Path, bid_uid: str) -> dict[str, float | int]:
    reader = MdbReader()
    try:
        started = time.perf_counter()
        data = reader.get_cover_sheet_data(str(path), bid_uid)
        data_load_seconds = time.perf_counter() - started
    finally:
        reader.close_connection(str(path))
    if data is None:
        raise ValueError(f"Bid {bid_uid} was not found in {path}")
    return _measure(
        data,
        lambda _path: [],
        data_load_seconds=data_load_seconds,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Profile Cover Sheet construction without changing project data."
    )
    parser.add_argument(
        "--rows",
        default="10,100,500,1000",
        help="Comma-separated synthetic page counts.",
    )
    parser.add_argument(
        "--metadata-delay-ms",
        type=float,
        default=0.0,
        help="Simulated PDF provider latency; startup should still make zero calls.",
    )
    parser.add_argument(
        "--mdb",
        type=Path,
        help="Optional MDB to profile through read-only Cover Sheet queries.",
    )
    parser.add_argument(
        "--bid-uid",
        help="Bid UID required with --mdb.",
    )
    args = parser.parse_args()
    if bool(args.mdb) != bool(args.bid_uid):
        parser.error("--mdb and --bid-uid must be supplied together")
    if args.mdb is not None and not args.mdb.is_file():
        parser.error(f"MDB does not exist: {args.mdb}")
    if args.metadata_delay_ms < 0:
        parser.error("--metadata-delay-ms cannot be negative")
    try:
        row_counts = [int(value) for value in args.rows.split(",")]
    except ValueError:
        parser.error("--rows must be a comma-separated list of integers")
    if not row_counts or any(count <= 0 for count in row_counts):
        parser.error("--rows values must be positive")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    print(
        "rows\tdata_load_seconds\tconstruction_seconds\tlayout_seconds\ttotal_seconds"
        "\tprovider_calls\tqwidgets\tqcomboboxes"
    )
    if args.mdb is not None:
        results = [_profile_mdb(args.mdb, args.bid_uid)]
    else:
        results = [
            _profile_synthetic(page_count, args.metadata_delay_ms)
            for page_count in row_counts
        ]
    for result in results:
        print(
            f"{result['rows']}\t{result['data_load_seconds']:.6f}"
            f"\t{result['construction_seconds']:.6f}"
            f"\t{result['layout_seconds']:.6f}\t{result['total_seconds']:.6f}"
            f"\t{result['provider_calls']}\t{result['qwidgets']}"
            f"\t{result['qcomboboxes']}"
        )
    app.processEvents()


if __name__ == "__main__":
    main()
