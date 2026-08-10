import os
import threading
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional
from PySide6.QtGui import QImage
from ....domain.entities.file_extensions import is_pdf_suffix
from ..utils.image_effects import tint_image
from .renderers.page_renderer import PageRenderer

_MIB = 1024 * 1024
_RENDERED_PLAN_PAGE_TARGET_ENTRIES = 20
_REPRESENTATIVE_PLAN_SHEET_BYTES = 80 * _MIB
_PAGE_CACHE_MAX_BYTES = (
    _RENDERED_PLAN_PAGE_TARGET_ENTRIES * _REPRESENTATIVE_PLAN_SHEET_BYTES
)
_PAGE_CACHE_MAX_SINGLE_IMAGE_BYTES = 96 * _MIB
_FRAME_CACHE_MAX_BYTES = 8 * _REPRESENTATIVE_PLAN_SHEET_BYTES
_FRAME_CACHE_MAX_SINGLE_IMAGE_BYTES = 96 * _MIB
_TINTED_CACHE_MAX_BYTES = 8 * _REPRESENTATIVE_PLAN_SHEET_BYTES
_TINTED_CACHE_MAX_SINGLE_IMAGE_BYTES = _PAGE_CACHE_MAX_SINGLE_IMAGE_BYTES
_PREFETCH_SHARED_CACHE_MAX_BYTES = _PAGE_CACHE_MAX_BYTES
_BASE_RASTER_MAX_PIXELS = 20_000_000
_IMAGE_BYTES_PER_PIXEL = 4
_CACHEABLE_RENDER_HEADROOM = 0.95
_CANCEL_TOKEN_KEY = "native_cancel_token"
_render_context = threading.local()
_FileSignature = Optional[tuple[int, int]]
_PageMetadataCacheKey = tuple[str, _FileSignature, int]
_PageCountCacheKey = tuple[str, _FileSignature]


@contextmanager
def scoped_pdf_render_cancellation_token(native_cancel_token) -> Iterator[None]:
    state = _render_context.__dict__
    had_previous = _CANCEL_TOKEN_KEY in state
    previous_token = state.get(_CANCEL_TOKEN_KEY)
    state[_CANCEL_TOKEN_KEY] = native_cancel_token
    try:
        yield
    finally:
        if had_previous:
            state[_CANCEL_TOKEN_KEY] = previous_token
        else:
            state.pop(_CANCEL_TOKEN_KEY, None)


def _current_pdf_render_cancel_token():
    return _render_context.__dict__.get(_CANCEL_TOKEN_KEY)


@dataclass(frozen=True)
class CacheKey:
    file_path: str
    file_signature: _FileSignature
    page_index: int
    scale: float
    rotation: int


@dataclass(frozen=True)
class FrameCacheKey:
    file_path: str
    file_signature: _FileSignature
    page_index: int
    scale: float
    rotation: int
    frame_x_pts: float
    frame_y_pts: float
    frame_w_pts: float
    frame_h_pts: float


@dataclass(frozen=True)
class TintedCacheKey:
    file_path: str
    file_signature: _FileSignature
    page_index: int
    scale: float
    rotation: int
    tint_r: int
    tint_g: int
    tint_b: int


class PageCache:
    MAX_ENTRIES = _RENDERED_PLAN_PAGE_TARGET_ENTRIES
    MAX_METADATA_ENTRIES = 512
    REPRESENTATIVE_PLAN_SHEET_BYTES = _REPRESENTATIVE_PLAN_SHEET_BYTES
    BASE_RASTER_MAX_PIXELS = _BASE_RASTER_MAX_PIXELS
    PAGE_CACHE_MAX_SINGLE_IMAGE_BYTES = _PAGE_CACHE_MAX_SINGLE_IMAGE_BYTES
    FRAME_CACHE_MAX_SINGLE_IMAGE_BYTES = _FRAME_CACHE_MAX_SINGLE_IMAGE_BYTES
    PREFETCH_SHARED_CACHE_MAX_BYTES = _PREFETCH_SHARED_CACHE_MAX_BYTES

    def __init__(self):
        self._cache: OrderedDict[CacheKey, QImage] = OrderedDict()
        self._frame_cache: OrderedDict[FrameCacheKey, QImage] = OrderedDict()
        self._tinted_cache: OrderedDict[TintedCacheKey, QImage] = OrderedDict()
        self._page_info_cache: OrderedDict[_PageMetadataCacheKey, Dict] = OrderedDict()
        self._page_count_cache: OrderedDict[_PageCountCacheKey, int] = OrderedDict()
        self._page_size_cache: OrderedDict[_PageMetadataCacheKey, tuple] = OrderedDict()
        self._text_runs_cache: OrderedDict[_PageMetadataCacheKey, list] = OrderedDict()
        self._lock = threading.Lock()
        self._local = threading.local()
        self._renderers: List[PageRenderer] = []
        self._renderers_lock = threading.Lock()
        self._in_flight: set[CacheKey] = set()
        self._frame_in_flight: set[FrameCacheKey] = set()
        self._in_flight_condition = threading.Condition(self._lock)

    def _get_renderer(self) -> PageRenderer:
        renderer = self._local.__dict__.get("renderer")
        if renderer is not None:
            return renderer
        renderer = PageRenderer()
        self._local.renderer = renderer
        with self._renderers_lock:
            self._renderers.append(renderer)
        return renderer

    def _quantize_scale(self, scale: float) -> float:
        return max(0.1, round(scale, 3))

    @staticmethod
    def _clean_page_index(page_index: int) -> int:
        return max(0, int(page_index or 0))

    def _normalize_page_index(
        self,
        file_path: str,
        page_index: int,
        file_signature: _FileSignature,
    ) -> int:
        requested_index = self._clean_page_index(page_index)
        if requested_index == 0:
            return 0
        if not is_pdf_suffix(file_path):
            return 0
        if file_signature is None:
            return requested_index
        page_count = self._get_page_count(file_path, file_signature)
        if page_count <= 0:
            return 0
        return min(requested_index, page_count - 1)

    @staticmethod
    def _quantize_frame_coord(value: float) -> float:
        return round(float(value), 3)

    def _build_frame_cache_key(
        self,
        file_path: str,
        page_index: int,
        scale: float,
        frame_x_pts: float,
        frame_y_pts: float,
        frame_w_pts: float,
        frame_h_pts: float,
        rotation: int,
    ) -> FrameCacheKey:
        file_signature = self._file_signature(file_path)
        normalized_page_index = self._normalize_page_index(
            file_path, page_index, file_signature
        )
        return FrameCacheKey(
            file_path=file_path,
            file_signature=file_signature,
            page_index=normalized_page_index,
            scale=self._quantize_scale(scale),
            rotation=rotation,
            frame_x_pts=self._quantize_frame_coord(frame_x_pts),
            frame_y_pts=self._quantize_frame_coord(frame_y_pts),
            frame_w_pts=self._quantize_frame_coord(frame_w_pts),
            frame_h_pts=self._quantize_frame_coord(frame_h_pts),
        )

    @staticmethod
    def _file_signature(file_path: str) -> _FileSignature:
        try:
            stat = os.stat(file_path)
        except OSError:
            return None
        return int(stat.st_mtime_ns), int(stat.st_size)

    def file_signature(self, file_path: str) -> _FileSignature:
        return self._file_signature(file_path)

    def get_page(
        self,
        file_path: str,
        page_index: int = 0,
        scale: float = 1.0,
        rotation: int = 0,
        wait_for_in_flight: bool = True,
    ) -> Optional[QImage]:
        if not file_path:
            return None
        quantized_scale = self._quantize_scale(scale)
        file_signature = self._file_signature(file_path)
        normalized_page_index = self._normalize_page_index(
            file_path, page_index, file_signature
        )
        key = CacheKey(
            file_path, file_signature, normalized_page_index, quantized_scale, rotation
        )
        track_in_flight = True
        with self._in_flight_condition:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            if key in self._in_flight and wait_for_in_flight:
                while key in self._in_flight:
                    self._in_flight_condition.wait()
                    if key in self._cache:
                        self._cache.move_to_end(key)
                        return self._cache[key]
            elif key in self._in_flight:
                track_in_flight = False
            if track_in_flight:
                self._in_flight.add(key)
        image = None
        try:
            renderer = self._get_renderer()
            image = renderer.render(
                file_path,
                normalized_page_index,
                quantized_scale,
                rotation,
                native_cancel_token=_current_pdf_render_cancel_token(),
            )
        finally:
            with self._in_flight_condition:
                if track_in_flight:
                    self._in_flight.discard(key)
                if image:
                    self._store_cache_image(
                        self._cache,
                        key,
                        image,
                        _PAGE_CACHE_MAX_BYTES,
                        _PAGE_CACHE_MAX_SINGLE_IMAGE_BYTES,
                    )
                self._in_flight_condition.notify_all()
        return image

    def _can_accept_prefetch_locked(self, estimated_bytes: int) -> bool:
        return (
            len(self._cache) < self.MAX_ENTRIES
            and self._cache_size_bytes(self._cache) + estimated_bytes
            <= _PAGE_CACHE_MAX_BYTES
            and self._combined_image_cache_size_bytes() + estimated_bytes
            <= _PREFETCH_SHARED_CACHE_MAX_BYTES
        )

    def _combined_image_cache_size_bytes(self) -> int:
        return (
            self._cache_size_bytes(self._cache)
            + self._cache_size_bytes(self._frame_cache)
            + self._cache_size_bytes(self._tinted_cache)
        )

    def can_accept_prefetch_render(
        self,
        width_pts: float,
        height_pts: float,
        scale: float,
        *,
        tinted: bool = False,
    ) -> bool:
        max_single_bytes = (
            _TINTED_CACHE_MAX_SINGLE_IMAGE_BYTES
            if tinted
            else _PAGE_CACHE_MAX_SINGLE_IMAGE_BYTES
        )
        estimated_bytes = self.estimated_render_bytes(width_pts, height_pts, scale)
        if estimated_bytes > max_single_bytes:
            return False
        with self._lock:
            return self._can_accept_prefetch_locked(estimated_bytes)

    @classmethod
    def cacheable_base_render_scale(
        cls,
        width_pts: float,
        height_pts: float,
        desired_scale: float,
        *,
        tinted: bool = False,
    ) -> float:
        return cls.cacheable_render_scale(
            width_pts,
            height_pts,
            desired_scale,
            max_pixels=cls.BASE_RASTER_MAX_PIXELS,
            tinted=tinted,
        )

    @staticmethod
    def cacheable_render_scale(
        width_pts: float,
        height_pts: float,
        desired_scale: float,
        *,
        max_pixels: Optional[int] = None,
        tinted: bool = False,
    ) -> float:
        if width_pts <= 0.0 or height_pts <= 0.0 or desired_scale <= 0.0:
            return desired_scale
        max_single_bytes = (
            _TINTED_CACHE_MAX_SINGLE_IMAGE_BYTES
            if tinted
            else _PAGE_CACHE_MAX_SINGLE_IMAGE_BYTES
        )
        max_scale_by_bytes = (
            (max_single_bytes * _CACHEABLE_RENDER_HEADROOM)
            / (width_pts * height_pts * _IMAGE_BYTES_PER_PIXEL)
        ) ** 0.5
        max_scale = max_scale_by_bytes
        if max_pixels is not None and max_pixels > 0:
            max_scale_by_pixels = (max_pixels / (width_pts * height_pts)) ** 0.5
            max_scale = min(max_scale, max_scale_by_pixels)
        clamped = max(0.1, min(desired_scale, max_scale))
        return int(clamped * 1000) / 1000

    @staticmethod
    def estimated_render_bytes(
        width_pts: float,
        height_pts: float,
        scale: float,
    ) -> int:
        if width_pts <= 0.0 or height_pts <= 0.0 or scale <= 0.0:
            return 0
        width_px = max(1, int(width_pts * scale + 0.999999))
        height_px = max(1, int(height_pts * scale + 0.999999))
        return width_px * height_px * _IMAGE_BYTES_PER_PIXEL

    def get_tinted_page(
        self,
        file_path: str,
        page_index: int = 0,
        scale: float = 1.0,
        rotation: int = 0,
        tint_rgb: tuple = (255, 80, 80),
        wait_for_in_flight: bool = True,
    ) -> Optional[QImage]:
        if not file_path:
            return None
        quantized_scale = self._quantize_scale(scale)
        r, g, b = tint_rgb
        file_signature = self._file_signature(file_path)
        normalized_page_index = self._normalize_page_index(
            file_path, page_index, file_signature
        )
        key = TintedCacheKey(
            file_path,
            file_signature,
            normalized_page_index,
            quantized_scale,
            rotation,
            r,
            g,
            b,
        )
        with self._lock:
            if key in self._tinted_cache:
                self._tinted_cache.move_to_end(key)
                return self._tinted_cache[key]
        base_image = self.get_page(
            file_path,
            normalized_page_index,
            scale,
            rotation,
            wait_for_in_flight=wait_for_in_flight,
        )
        if not base_image:
            return None
        tinted = tint_image(base_image, r, g, b)
        with self._lock:
            self._store_cache_image(
                self._tinted_cache,
                key,
                tinted,
                _TINTED_CACHE_MAX_BYTES,
                _TINTED_CACHE_MAX_SINGLE_IMAGE_BYTES,
            )
        return tinted

    def get_frame(
        self,
        file_path: str,
        page_index: int,
        scale: float,
        frame_x_pts: float,
        frame_y_pts: float,
        frame_w_pts: float,
        frame_h_pts: float,
        rotation: int = 0,
        wait_for_in_flight: bool = True,
    ) -> Optional[QImage]:
        if not file_path or frame_w_pts <= 0.0 or frame_h_pts <= 0.0:
            return None
        key = self._build_frame_cache_key(
            file_path,
            page_index,
            scale,
            frame_x_pts,
            frame_y_pts,
            frame_w_pts,
            frame_h_pts,
            rotation,
        )
        track_in_flight = True
        with self._in_flight_condition:
            if key in self._frame_cache:
                self._frame_cache.move_to_end(key)
                return self._frame_cache[key]
            if key in self._frame_in_flight and wait_for_in_flight:
                while key in self._frame_in_flight:
                    self._in_flight_condition.wait()
                    if key in self._frame_cache:
                        self._frame_cache.move_to_end(key)
                        return self._frame_cache[key]
            elif key in self._frame_in_flight:
                track_in_flight = False
            if track_in_flight:
                self._frame_in_flight.add(key)
        image = None
        try:
            renderer = self._get_renderer()
            image = renderer.render_frame(
                key.file_path,
                key.page_index,
                key.scale,
                key.frame_x_pts,
                key.frame_y_pts,
                key.frame_w_pts,
                key.frame_h_pts,
                key.rotation,
                native_cancel_token=_current_pdf_render_cancel_token(),
            )
        finally:
            with self._in_flight_condition:
                if track_in_flight:
                    self._frame_in_flight.discard(key)
                if image:
                    self._store_cache_image(
                        self._frame_cache,
                        key,
                        image,
                        _FRAME_CACHE_MAX_BYTES,
                        _FRAME_CACHE_MAX_SINGLE_IMAGE_BYTES,
                    )
                self._in_flight_condition.notify_all()
        return image

    def get_page_info(self, file_path: str, page_index: int = 0) -> Dict:
        file_signature = self._file_signature(file_path)
        normalized_page_index = self._normalize_page_index(
            file_path, page_index, file_signature
        )
        cache_key = (file_path, file_signature, normalized_page_index)
        with self._lock:
            if cache_key in self._page_info_cache:
                self._page_info_cache.move_to_end(cache_key)
                return self._page_info_cache[cache_key]
        renderer = self._get_renderer()
        info = renderer.get_page_info(file_path, normalized_page_index)
        with self._lock:
            self._store_lru(self._page_info_cache, cache_key, info)
        return info

    def _store_cache_image(
        self,
        cache: OrderedDict,
        key,
        image: QImage,
        max_bytes: int,
        max_single_image_bytes: int,
    ) -> None:
        if self._image_size_bytes(image) > max_single_image_bytes:
            return
        cache[key] = image
        cache.move_to_end(key)
        while self._cache_exceeds_budget(cache, max_bytes):
            cache.popitem(last=False)

    def _cache_exceeds_budget(self, cache: OrderedDict, max_bytes: int) -> bool:
        return (
            len(cache) > self.MAX_ENTRIES or self._cache_size_bytes(cache) > max_bytes
        )

    def _cache_size_bytes(self, cache: OrderedDict) -> int:
        return sum(self._image_size_bytes(image) for image in cache.values())

    @staticmethod
    def _image_size_bytes(image: QImage) -> int:
        if image.isNull():
            return 0
        return int(image.sizeInBytes())

    def _store_lru(self, cache: OrderedDict, key, value) -> None:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > self.MAX_METADATA_ENTRIES:
            cache.popitem(last=False)

    def _get_page_count(self, file_path: str, file_signature: _FileSignature) -> int:
        cache_key = (file_path, file_signature)
        with self._lock:
            if cache_key in self._page_count_cache:
                self._page_count_cache.move_to_end(cache_key)
                return self._page_count_cache[cache_key]
        renderer = self._get_renderer()
        count = renderer.get_page_count(file_path)
        with self._lock:
            self._store_lru(self._page_count_cache, cache_key, count)
        return count

    def get_page_size(self, file_path: str, page_index: int = 0) -> tuple[float, float]:
        file_signature = self._file_signature(file_path)
        normalized_page_index = self._normalize_page_index(
            file_path, page_index, file_signature
        )
        cache_key = (file_path, file_signature, normalized_page_index)
        with self._lock:
            if cache_key in self._page_size_cache:
                self._page_size_cache.move_to_end(cache_key)
                return self._page_size_cache[cache_key]
        renderer = self._get_renderer()
        size = renderer.get_page_size(file_path, normalized_page_index)
        with self._lock:
            self._store_lru(self._page_size_cache, cache_key, size)
        return size

    def get_text_runs(self, file_path: str, page_index: int = 0) -> list:
        file_signature = self._file_signature(file_path)
        normalized_page_index = self._normalize_page_index(
            file_path, page_index, file_signature
        )
        cache_key = (file_path, file_signature, normalized_page_index)
        with self._lock:
            if cache_key in self._text_runs_cache:
                self._text_runs_cache.move_to_end(cache_key)
                return list(self._text_runs_cache[cache_key])
        renderer = self._get_renderer()
        text_runs = renderer.extract_text_runs(file_path, normalized_page_index)
        with self._lock:
            self._store_lru(self._text_runs_cache, cache_key, list(text_runs))
        return list(text_runs)

    def clear(self):
        with self._lock:
            self._cache.clear()
            self._frame_cache.clear()
            self._tinted_cache.clear()
            self._page_info_cache.clear()
            self._page_count_cache.clear()
            self._page_size_cache.clear()
            self._text_runs_cache.clear()
        with self._renderers_lock:
            renderers = tuple(self._renderers)
            self._renderers.clear()
            self._local = threading.local()
        first_error = None
        for renderer in renderers:
            try:
                renderer.close()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error
