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


@dataclass(frozen=True)
class CacheKey:
    file_path: str
    page_index: int
    scale: float
    rotation: int


@dataclass(frozen=True)
class TintedCacheKey:
    file_path: str
    page_index: int
    scale: float
    rotation: int
    tint_r: int
    tint_g: int
    tint_b: int


class PageCache:
    MAX_ENTRIES = 20

    def __init__(self):
        self._cache: OrderedDict[CacheKey, QImage] = OrderedDict()
        self._tinted_cache: OrderedDict[TintedCacheKey, QImage] = OrderedDict()
        self._page_info_cache: Dict[str, Dict] = {}
        self._page_count_cache: Dict[str, int] = {}
        self._page_size_cache: Dict[str, tuple] = {}
        self._lock = threading.Lock()
        self._local = threading.local()
        self._renderers: List[PageRenderer] = []
        self._renderers_lock = threading.Lock()
        self._in_flight: set[CacheKey] = set()
        self._in_flight_condition = threading.Condition(self._lock)

    def _get_renderer(self) -> PageRenderer:
        try:
            return self._local.renderer
        except AttributeError:
            renderer = PageRenderer()
            self._local.renderer = renderer
            with self._renderers_lock:
                self._renderers.append(renderer)
            return renderer

    def _quantize_scale(self, scale: float) -> float:
        return max(0.1, round(scale, 3))

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
        key = CacheKey(file_path, page_index, quantized_scale, rotation)
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
        key = TintedCacheKey(file_path, page_index, quantized_scale, rotation, r, g, b)
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

    def render_region_uncached(
        self,
        file_path: str,
        page_index: int,
        scale: float,
        tile_x: int,
        tile_y: int,
        tile_w: int,
        tile_h: int,
        rotation: int = 0,
    ) -> Optional[QImage]:
        if not file_path:
            return None
        quantized_scale = self._quantize_scale(scale)
        return self._get_renderer().render_region(
            file_path,
            page_index,
            quantized_scale,
            tile_x,
            tile_y,
            tile_w,
            tile_h,
            rotation,
        )

    def get_page_info(self, file_path: str, page_index: int = 0) -> Dict:
        cache_key = f"{file_path}:{page_index}"
        with self._lock:
            if cache_key in self._page_info_cache:
                return self._page_info_cache[cache_key]
        renderer = self._get_renderer()
        info = renderer.get_page_info(file_path, page_index)
        with self._lock:
            self._page_info_cache[cache_key] = info
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

    def get_page_count(self, file_path: str) -> int:
        with self._lock:
            if file_path in self._page_count_cache:
                return self._page_count_cache[file_path]
        renderer = self._get_renderer()
        count = renderer.get_page_count(file_path)
        with self._lock:
            self._page_count_cache[file_path] = count
        return count

    def get_page_size(self, file_path: str, page_index: int = 0) -> tuple:
        cache_key = f"{file_path}:{page_index}"
        with self._lock:
            if cache_key in self._page_size_cache:
                return self._page_size_cache[cache_key]
        renderer = self._get_renderer()
        size = renderer.get_page_size(file_path, page_index)
        with self._lock:
            self._page_size_cache[cache_key] = size
        return size

    def clear(self):
        with self._lock:
            self._cache.clear()
            self._tinted_cache.clear()
            self._page_info_cache.clear()
            self._page_count_cache.clear()
            self._page_size_cache.clear()
        with self._renderers_lock:
            for renderer in self._renderers:
                renderer.close()
            self._renderers.clear()
        self._local = threading.local()
