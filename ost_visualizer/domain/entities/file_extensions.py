from pathlib import Path

PDF_EXTENSION = ".pdf"
CSV_EXTENSION = ".csv"
TIF_EXTENSION = ".tif"
TIFF_EXTENSION = ".tiff"
TIFF_EXTENSIONS = frozenset({TIF_EXTENSION, TIFF_EXTENSION})
OSP_IMAGE_EXTENSIONS = frozenset({PDF_EXTENSION, TIF_EXTENSION, TIFF_EXTENSION})


def normalized_suffix(path) -> str:
    return Path(path).suffix.lower()


def _suffix_from_value(value) -> str:
    text = str(value or "").lower()
    if text.startswith(".") and "/" not in text and "\\" not in text:
        return text
    return normalized_suffix(text)


def is_pdf_suffix(value) -> bool:
    return _suffix_from_value(value) == PDF_EXTENSION


def is_csv_suffix(value) -> bool:
    return _suffix_from_value(value) == CSV_EXTENSION


def is_tiff_suffix(value) -> bool:
    return _suffix_from_value(value) in TIFF_EXTENSIONS
