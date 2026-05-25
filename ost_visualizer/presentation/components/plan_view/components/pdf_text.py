from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class PdfTextRect:
    left: float
    top: float
    right: float
    bottom: float

    def contains(self, x: float, y: float) -> bool:
        return self.left <= x <= self.right and self.top <= y <= self.bottom


@dataclass(frozen=True)
class PdfTextChar(PdfTextRect):
    text: str


@dataclass(frozen=True)
class PdfTextRun(PdfTextRect):
    text: str
    chars: Tuple[PdfTextChar, ...]


@dataclass(frozen=True)
class PdfTextSelection:
    text: str
    rects: Tuple[PdfTextRect, ...]

    @property
    def is_empty(self) -> bool:
        return not self.text or not self.rects
