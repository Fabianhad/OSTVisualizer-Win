import base64
import json
import os
import tempfile
import time
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional
from .....application.dtos.html_export_page_dto import HtmlExportPageDto
from .....application.dtos.scene_data_dto import SceneData, ScenePageImageLayer
from .....application.interfaces.i_color_service import IColorService
from .....application.interfaces.i_coordinate_transformer import ICoordinateTransformer
from .....application.interfaces.i_takeoff_domain_service import ITakeoffDomainService
from .....domain.entities.config import Config
from .....domain.entities.condition import Condition
from .....domain.entities.area import BidArea
from .....domain.entities.layer import BidLayer
from .....domain.entities.takeoff import Takeoff
from .adapters.threejs_mesh_adapter import ThreejsMeshAdapter
from .mesh_processor import process_meshes_for_threejs
from .two_d_takeoff_processor import process_takeoffs_2d_for_threejs


def visualize_with_threejs(
    bid_conditions: Dict[str, Condition],
    bid_takeoffs: List[Takeoff],
    coord_system: ICoordinateTransformer,
    color_service: IColorService,
    takeoff_service: ITakeoffDomainService,
    title: str = "OST Takeoff 3D Visualization",
    output_path: Optional[str] = None,
    auto_open: bool = True,
    bid_name: Optional[str] = None,
    color_mode: str = Config.COLOR_MODE_SOLID,
    grayscale_enabled: bool = True,
    page_area_selections: Optional[Dict] = None,
    pages: Optional[List[HtmlExportPageDto]] = None,
    active_page_uid: str = "",
    layers: Optional[List[BidLayer]] = None,
    areas: Optional[List[BidArea]] = None,
    page_image_layer: Optional[ScenePageImageLayer] = None,
) -> Optional[str]:
    start_time = time.time()
    if not bid_conditions or not bid_takeoffs:
        return None
    processed_meshes, bounds = process_meshes_for_threejs(
        bid_conditions,
        bid_takeoffs,
        coord_system,
        color_service=color_service,
        takeoff_service=takeoff_service,
        color_mode=color_mode,
        grayscale_enabled=grayscale_enabled,
        page_area_selections=page_area_selections,
        areas=areas,
    )
    if not processed_meshes:
        return None
    adapter = ThreejsMeshAdapter(color_service)
    scene_data = adapter.build_scene_data(
        processed_meshes,
        bounds,
        title,
        layers=layers,
        areas=areas,
        page_image_layer=page_image_layer,
    )
    page_entries, pdf_documents, takeoffs_2d = _build_multi_page_data(
        pages or [],
        bid_conditions,
        bid_takeoffs,
        color_service,
        takeoff_service,
        color_mode,
        grayscale_enabled,
        page_area_selections,
    )
    if page_entries:
        exported_page_uids = [page["uid"] for page in page_entries]
        scene_data["pages"] = page_entries
        scene_data["selected_page_uids"] = exported_page_uids
        scene_data["active_page_uid"] = (
            active_page_uid
            if active_page_uid in exported_page_uids
            else exported_page_uids[0]
        )
        scene_data["takeoffs_2d"] = takeoffs_2d
        if pdf_documents:
            scene_data["pdf_documents"] = pdf_documents
    html_content = _generate_html(scene_data, title)
    if output_path is None:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".html")
        output_path = temp_file.name
        temp_file.close()
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    if auto_open:
        webbrowser.open(f"file://{os.path.abspath(output_path)}")
    elapsed = time.time() - start_time
    return output_path


def _build_multi_page_data(
    pages: List[HtmlExportPageDto],
    bid_conditions: Dict[str, Condition],
    bid_takeoffs: List[Takeoff],
    color_service: IColorService,
    takeoff_service: ITakeoffDomainService,
    color_mode: str,
    grayscale_enabled: bool,
    page_area_selections: Optional[Dict],
):
    page_entries = []
    takeoffs_2d = []
    pdf_documents_by_path: Dict[str, str] = {}
    pdf_documents = []
    takeoffs_by_page: Dict[str, List[Takeoff]] = {}
    for takeoff in bid_takeoffs:
        takeoffs_by_page.setdefault(takeoff.page_uid or "", []).append(takeoff)
    for page in pages:
        page_uid = str(page["uid"])
        pdf_document_uid = ""
        pdf_path = page.get("pdf_path")
        if pdf_path and os.path.isfile(pdf_path):
            normalized_pdf_path = os.path.abspath(pdf_path)
            pdf_document_uid = pdf_documents_by_path.get(normalized_pdf_path, "")
            if not pdf_document_uid:
                try:
                    with open(normalized_pdf_path, "rb") as pf:
                        data_base64 = base64.b64encode(pf.read()).decode("ascii")
                except OSError:
                    data_base64 = ""
                if data_base64:
                    pdf_document_uid = f"pdf-{len(pdf_documents) + 1}"
                    pdf_documents_by_path[normalized_pdf_path] = pdf_document_uid
                    pdf_documents.append(
                        {"uid": pdf_document_uid, "data_base64": data_base64}
                    )
        page_entries.append(
            {
                "uid": page_uid,
                "label": str(page["label"] or page_uid),
                "name": str(page["name"] or ""),
                "sheet_no": str(page["sheet_no"] or ""),
                "sequence": int(page["sequence"] or 0),
                "width": float(page["width"] or 0.0),
                "height": float(page["height"] or 0.0),
                "page_width": float(page["page_width"] or 0.0),
                "page_height": float(page["page_height"] or 0.0),
                "image_layer_uid": str(page["image_layer_uid"] or ""),
                "visible": True,
                "pdf_document_uid": pdf_document_uid,
                "pdf_page_index": int(page["pdf_page_index"] or 0),
            }
        )
        if page["width"] > 0 and page["height"] > 0:
            page_info = {
                "scale_factor1": 1.0,
                "scale_factor2": page["scale_ratio"] or 1.0,
                "rotation": page["rotation"],
                "flip_x": page["flip_x"],
                "flip_y": page["flip_y"],
                "width": page["width"],
                "height": page["height"],
                "view_scale": 1.0,
            }
            takeoffs_2d.extend(
                process_takeoffs_2d_for_threejs(
                    bid_conditions,
                    takeoffs_by_page.get(page_uid, []),
                    color_service,
                    takeoff_service,
                    page_info,
                    color_mode=color_mode,
                    grayscale_enabled=grayscale_enabled,
                    page_area_selections=page_area_selections,
                )
            )
    return page_entries, pdf_documents, takeoffs_2d


def _generate_html(scene_data: SceneData, title: str) -> str:
    template_path = Path(__file__).parent / "templates" / "viewer.html"
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()
    scene_json = json.dumps(scene_data, separators=(",", ":"))
    html = template.replace("{{TITLE}}", title)
    html = html.replace("{{SCENE_DATA}}", scene_json)
    return html
