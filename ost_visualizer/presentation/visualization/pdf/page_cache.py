import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, List, Optional
from PySide6.QtGui import QImage
from ..utils.image_effects import tint_image
from .renderers.page_renderer import PageRenderer

_PAGE_CACHE_MAX_BYTES = 160 * 1024 * 1024
_PAGE_CACHE_MAX_SINGLE_IMAGE_BYTES = 96 * 1024 * 1024
_TINTED_CACHE_MAX_BYTES = 64 * 1024 * 1024
_TINTED_CACHE_MAX_SINGLE_IMAGE_BYTES = 32 * 1024 * 1024
_BASE_RASTER_MAX_PIXELS = 20_000_000
_IMAGE_BYTES_PER_PIXEL = 4
_CACHEABLE_RENDER_HEADROOM = 0.95


@dataclass(frozen=True)
class CacheKey:
    file_path: str
    file_signature: Optional[tuple[int, int]]
    page_index: int
    scale: float
    rotation: int


@dataclass(frozen=True)
class TintedCacheKey:
    file_path: str
    file_signature: Optional[tuple[int, int]]
    page_index: int
    scale: float
    rotation: int
    tint_r: int
    tint_g: int
    tint_b: int


class PageCache:
    MAX_ENTRIES = 20
    MAX_METADATA_ENTRIES = 512
    BASE_RASTER_MAX_PIXELS = _BASE_RASTER_MAX_PIXELS
    PAGE_CACHE_MAX_SINGLE_IMAGE_BYTES = _PAGE_CACHE_MAX_SINGLE_IMAGE_BYTES

    def __init__(self):
        self._cache: OrderedDict[CacheKey, QImage] = OrderedDict()
        self._tinted_cache: OrderedDict[TintedCacheKey, QImage] = OrderedDict()
        self._page_info_cache: OrderedDict[str, Dict] = OrderedDict()
        self._page_count_cache: OrderedDict[str, int] = OrderedDict()
        self._page_size_cache: OrderedDict[str, tuple] = OrderedDict()
        self._text_runs_cache: OrderedDict[str, list] = OrderedDict()
        self._lock = threading.Lock()
        self._local = threading.local()
        self._renderers: List[PageRenderer] = []
        self._renderers_lock = threading.Lock()
        self._in_flight: set[CacheKey] = set()
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
    def _file_signature(file_path: str) -> Optional[tuple[int, int]]:
        try:
            stat = os.stat(file_path)
        except OSError:
            return None
        return int(stat.st_mtime_ns), int(stat.st_size)

    def get_page(
        self,
        file_path: str,
        page_index: int = 0,
        scale: float = 1.0,
        rotation: int = 0,
    ) -> Optional[QImage]:
        if not file_path:
            return None
        quantized_scale = self._quantize_scale(scale)
        file_signature = self._file_signature(file_path)
        key = CacheKey(file_path, file_signature, page_index, quantized_scale, rotation)
        with self._in_flight_condition:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            while key in self._in_flight:
                self._in_flight_condition.wait()
                if key in self._cache:
                    self._cache.move_to_end(key)
                    return self._cache[key]
            self._in_flight.add(key)
        image = None
        try:
            renderer = self._get_renderer()
            image = renderer.render(file_path, page_index, quantized_scale, rotation)
        finally:
            with self._in_flight_condition:
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

    def can_accept_prefetch(self) -> bool:
        with self._lock:
            return (
                len(self._cache) < self.MAX_ENTRIES
                and self._cache_size_bytes(self._cache) < _PAGE_CACHE_MAX_BYTES
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
        if self.estimated_render_bytes(width_pts, height_pts, scale) > max_single_bytes:
            return False
        return self.can_accept_prefetch()

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
    ) -> Optional[QImage]:
        if not file_path:
            return None
        quantized_scale = self._quantize_scale(scale)
        r, g, b = tint_rgb
        file_signature = self._file_signature(file_path)
        key = TintedCacheKey(
            file_path, file_signature, page_index, quantized_scale, rotation, r, g, b
        )
        with self._lock:
            if key in self._tinted_cache:
                self._tinted_cache.move_to_end(key)
                return self._tinted_cache[key]
        base_image = self.get_page(file_path, page_index, scale, rotation)
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

    def render_uncached(
        self,
        file_path: str,
        page_index: int = 0,
        scale: float = 1.0,
        rotation: int = 0,
    ) -> Optional[QImage]:
        if not file_path:
            return None
        quantized_scale = self._quantize_scale(scale)
        return self._get_renderer().render(
            file_path, page_index, quantized_scale, rotation
        )

    def render_frame_uncached(
        self,
        file_path: str,
        page_index: int,
        scale: float,
        frame_x_pts: float,
        frame_y_pts: float,
        frame_w_pts: float,
        frame_h_pts: float,
        rotation: int = 0,
    ) -> Optional[QImage]:
        if not file_path:
            return None
        quantized_scale = self._quantize_scale(scale)
        return self._get_renderer().render_frame(
            file_path,
            page_index,
            quantized_scale,
            frame_x_pts,
            frame_y_pts,
            frame_w_pts,
            frame_h_pts,
            rotation,
        )

    def get_page_info(self, file_path: str, page_index: int = 0) -> Dict:
        cache_key = (file_path, self._file_signature(file_path), page_index)
        with self._lock:
            if cache_key in self._page_info_cache:
                self._page_info_cache.move_to_end(cache_key)
                return self._page_info_cache[cache_key]
        renderer = self._get_renderer()
        info = renderer.get_page_info(file_path, page_index)
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

    @staticmethod
    def _cache_size_bytes(cache: OrderedDict) -> int:
        return sum(PageCache._image_size_bytes(image) for image in cache.values())

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

    def get_page_count(self, file_path: str) -> int:
        cache_key = (file_path, self._file_signature(file_path))
        with self._lock:
            if cache_key in self._page_count_cache:
                self._page_count_cache.move_to_end(cache_key)
                return self._page_count_cache[cache_key]
        renderer = self._get_renderer()
        count = renderer.get_page_count(file_path)
        with self._lock:
            self._store_lru(self._page_count_cache, cache_key, count)
        return count

    def get_page_size(self, file_path: str, page_index: int = 0) -> tuple:
        cache_key = (file_path, self._file_signature(file_path), page_index)
        with self._lock:
            if cache_key in self._page_size_cache:
                self._page_size_cache.move_to_end(cache_key)
                return self._page_size_cache[cache_key]
        renderer = self._get_renderer()
        size = renderer.get_page_size(file_path, page_index)
        with self._lock:
            self._store_lru(self._page_size_cache, cache_key, size)
        return size

    def get_text_runs(self, file_path: str, page_index: int = 0) -> list:
        cache_key = (file_path, self._file_signature(file_path), page_index)
        with self._lock:
            if cache_key in self._text_runs_cache:
                self._text_runs_cache.move_to_end(cache_key)
                return list(self._text_runs_cache[cache_key])
        renderer = self._get_renderer()
        text_runs = renderer.extract_text_runs(file_path, page_index)
        with self._lock:
            self._store_lru(self._text_runs_cache, cache_key, list(text_runs))
        return list(text_runs)

    def clear(self):
        with self._lock:
            self._cache.clear()
            self._tinted_cache.clear()
            self._page_info_cache.clear()
            self._page_count_cache.clear()
            self._page_size_cache.clear()
            self._text_runs_cache.clear()
        with self._renderers_lock:
            for renderer in self._renderers:
                renderer.close()
            self._renderers.clear()
        self._local = threading.local()
