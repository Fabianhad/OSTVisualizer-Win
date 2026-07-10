from typing import List, Optional, Sequence
from ...domain.entities.file_extensions import is_pdf_suffix
from ...domain.entities.layer import IMAGE_LAYER_NAME
from ...domain.services.project_data_service import ProjectDataService
from ..dtos.page_visualization_page_dto import PageVisualizationPageDto
from ..dtos.scene_data_dto import ScenePageImageLayer


class PageVisualizationMetadataService:
    def __init__(self, project_data_service: ProjectDataService):
        self.project_data = project_data_service

    def build_pages(self, page_uids: Sequence[str]) -> List[PageVisualizationPageDto]:
        image_layer_uid = self.project_data.get_image_layer_uid() or IMAGE_LAYER_NAME
        pages: List[PageVisualizationPageDto] = []
        for page_uid in page_uids:
            page = self.project_data.get_page(page_uid)
            if not page:
                continue
            sf1 = page.scale_factor1 or 1.0
            sf2 = page.scale_factor2 or 1.0
            ratio = sf2 / sf1 if sf1 > 0 else 1.0
            pdf_path: Optional[str] = None
            if page.image_path and is_pdf_suffix(page.image_path):
                pdf_path = page.image_path
            pages.append(
                {
                    "uid": page.uid,
                    "label": self.format_page_label(page),
                    "name": page.name or "",
                    "sheet_no": page.sheet_no or "",
                    "sequence": int(page.sequence or 0),
                    "width": float(page.effective_width_pts or 0.0),
                    "height": float(page.effective_height_pts or 0.0),
                    "page_width": float((page.width_pts / 72.0) * ratio),
                    "page_height": float((page.height_pts / 72.0) * ratio),
                    "image_layer_uid": image_layer_uid,
                    "pdf_path": pdf_path,
                    "pdf_page_index": page.page_index,
                    "scale_ratio": ratio,
                    "rotation": int(page.rotation or 0),
                    "flip_x": bool(page.flip_x),
                    "flip_y": bool(page.flip_y),
                }
            )
        return pages

    def image_layer_visible(self, page_uids: Sequence[str]) -> bool:
        pages = [self.project_data.get_page(page_uid) for page_uid in page_uids]
        valid_pages = [page for page in pages if page]
        return (
            any(bool(page.layer_visible) for page in valid_pages)
            if valid_pages
            else True
        )

    def build_image_layer(self, page_uids: Sequence[str]) -> ScenePageImageLayer:
        image_layer_uid = self.project_data.get_image_layer_uid()
        return {
            "uid": image_layer_uid or IMAGE_LAYER_NAME,
            "name": IMAGE_LAYER_NAME.title(),
            "visible": self.image_layer_visible(page_uids),
        }

    def resolve_active_page(
        self, page_uids: Sequence[str], requested_uid: Optional[str]
    ) -> str:
        exported = {str(uid) for uid in page_uids}
        if requested_uid and requested_uid in exported:
            return requested_uid
        last_selected = self.project_data.get_last_selected_page_uid()
        if last_selected and last_selected in exported:
            return last_selected
        return str(page_uids[0]) if page_uids else ""

    @staticmethod
    def format_page_label(page) -> str:
        parts = []
        if page.sequence > 0:
            parts.append(str(page.sequence))
        if page.sheet_no:
            parts.append(str(page.sheet_no))
        if page.name:
            parts.append(page.name)
        return " - ".join(parts) if parts else str(page.uid)
