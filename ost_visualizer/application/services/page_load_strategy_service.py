from dataclasses import dataclass
from typing import Any, Dict
from ...application.interfaces.i_page_size_provider import IPageSizeProvider
from ...application.interfaces.i_page_load_strategy_service import ILoadStrategy
from ...application.render_quality import baseline_render_scale
from ...domain.entities.file_extensions import is_pdf_suffix
from ...domain.entities.page import Page


@dataclass
class LoadStrategy:
    needs_async_loading: bool
    view_scale: float
    show_canvas: bool
    pdf_width_pts: float
    pdf_height_pts: float
    placeholder_width: float
    placeholder_height: float
    main_scale: float
    load_composite: bool = False
    load_main: bool = False
    load_overlay: bool = False


class PageLoadStrategyService:
    def __init__(self, page_size_provider: IPageSizeProvider):
        self._page_size_provider = page_size_provider

    def determine_load_strategy(self, page: Page) -> LoadStrategy:
        has_image_file = page.has_image and page.image_path
        is_pdf = has_image_file and is_pdf_suffix(page.image_path)
        pdf_width_pts, pdf_height_pts = self._resolve_pdf_page_size(page, is_pdf)
        show_mode = page.image_show_mode
        show_original = show_mode in (0, 2)
        show_overlay = show_mode in (1, 2) and page.has_overlay
        page_has_dimensions = page.width_pts > 0 and page.height_pts > 0
        show_canvas = page_has_dimensions or not has_image_file
        view_scale = self._calculate_view_scale(
            page, show_mode, has_image_file, is_pdf, pdf_width_pts
        )
        main_scale = baseline_render_scale(is_pdf=is_pdf)
        placeholder_width, placeholder_height = self._calculate_placeholder_size(
            page,
            pdf_width_pts,
            pdf_height_pts,
            has_image_file,
            show_original,
            is_pdf,
            view_scale,
            main_scale,
        )
        load_composite = (
            has_image_file and show_original and show_mode == 2 and page.has_overlay
        )
        load_main = has_image_file and show_original and not load_composite
        load_overlay = (
            not (has_image_file and show_original) and show_overlay and page.has_overlay
        )
        needs_async_loading = bool(
            page.layer_visible and (load_composite or load_main or load_overlay)
        )
        return LoadStrategy(
            needs_async_loading=needs_async_loading,
            view_scale=view_scale,
            show_canvas=show_canvas,
            pdf_width_pts=pdf_width_pts,
            pdf_height_pts=pdf_height_pts,
            placeholder_width=placeholder_width,
            placeholder_height=placeholder_height,
            load_composite=load_composite,
            load_main=load_main,
            load_overlay=load_overlay,
            main_scale=main_scale,
        )

    def _calculate_view_scale(
        self,
        page: Page,
        show_mode: int,
        has_image_file: bool,
        is_pdf: bool,
        pdf_width_pts: float,
    ) -> float:
        if show_mode == 1 and page.has_overlay:
            is_overlay_pdf_file = is_pdf_suffix(page.overlay_image_path)
            if not is_overlay_pdf_file:
                native_width, _ = self._page_size_provider.get_page_size(
                    page.overlay_image_path, 0
                )
                if pdf_width_pts > 0 and native_width > 0:
                    return native_width / pdf_width_pts
            return baseline_render_scale(is_pdf=is_overlay_pdf_file)
        if has_image_file and not is_pdf:
            native_width, _ = self._page_size_provider.get_page_size(
                page.image_path, page.page_index
            )
            if pdf_width_pts > 0 and native_width > 0:
                return native_width / pdf_width_pts
            return baseline_render_scale(is_pdf=False)
        return baseline_render_scale(is_pdf=True)

    def _resolve_pdf_page_size(self, page: Page, is_pdf: bool) -> tuple[float, float]:
        fallback_width = page.width_pts if page.width_pts else 612.0
        fallback_height = page.height_pts if page.height_pts else 792.0
        if not (is_pdf and page.image_path):
            return fallback_width, fallback_height
        actual_width, actual_height = self._page_size_provider.get_page_size(
            page.image_path, page.page_index
        )
        if actual_width > 0 and actual_height > 0:
            return actual_width, actual_height
        return fallback_width, fallback_height

    def _calculate_placeholder_size(
        self,
        page: Page,
        pdf_width_pts: float,
        pdf_height_pts: float,
        has_image_file: bool,
        show_original: bool,
        is_pdf: bool,
        view_scale: float,
        main_scale: float,
    ) -> tuple[float, float]:
        fallback_width = pdf_width_pts * view_scale
        fallback_height = pdf_height_pts * view_scale
        if not (has_image_file and show_original):
            return fallback_width, fallback_height
        if is_pdf:
            placeholder_width = pdf_width_pts * main_scale
            placeholder_height = pdf_height_pts * main_scale
            if page.rotation in (90, 270):
                placeholder_width, placeholder_height = (
                    placeholder_height,
                    placeholder_width,
                )
            return placeholder_width, placeholder_height
        native_width, native_height = self._page_size_provider.get_page_size(
            page.image_path, page.page_index
        )
        if native_width <= 0 or native_height <= 0:
            return fallback_width, fallback_height
        return native_width * main_scale, native_height * main_scale

    def create_pending_page_data(
        self,
        page: Page,
        strategy: ILoadStrategy,
        pdf_width_pts: float,
        pdf_height_pts: float,
    ) -> Dict[str, Any]:
        return {
            "page": page,
            "rotation": page.rotation,
            "show_mode": page.image_show_mode,
            "show_overlay": page.image_show_mode in (1, 2) and page.has_overlay,
            "pdf_width_pts": pdf_width_pts,
            "pdf_height_pts": pdf_height_pts,
            "view_scale": strategy.view_scale,
        }
