import base64
import html
import json
import os
import tempfile
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from .....application.dtos.page_visualization_page_dto import PageVisualizationPageDto
from .....application.dtos.scene_data_dto import SceneData, ScenePageImageLayer
from .....application.interfaces.i_color_service import IColorService
from .....application.interfaces.i_coordinate_transformer import ICoordinateTransformer
from .....application.interfaces.i_takeoff_domain_service import ITakeoffDomainService
from .....domain.services.page_image_plane_transform import (
    resolve_page_floor_elevations,
    threejs_page_plane_transform,
)
from .....domain.entities.area import BidArea
from .....domain.entities.condition import Condition
from .....domain.entities.config import Config
from .....domain.entities.elevation_callout import (
    DEFAULT_ELEVATION_CALLOUT_SETTINGS,
    ElevationCalloutSettings,
)
from .....domain.entities.layer import BidLayer
from .....domain.entities.takeoff import Takeoff
from ...exporters import ost_pdf_writer
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
    display_mode_3d: str = Config.DISPLAY_MODE_SOLID,
    display_mode_2d: str = Config.DISPLAY_MODE_SOLID,
    display_modes_synced: bool = True,
    grayscale_enabled: bool = True,
    page_area_selections: Optional[Dict] = None,
    pages: Optional[List[PageVisualizationPageDto]] = None,
    active_page_uid: str = "",
    layers: Optional[List[BidLayer]] = None,
    areas: Optional[List[BidArea]] = None,
    page_image_layer: Optional[ScenePageImageLayer] = None,
    *,
    include_elevation_callouts: bool,
    elevation_callout_settings: ElevationCalloutSettings = (
        DEFAULT_ELEVATION_CALLOUT_SETTINGS
    ),
    elevation_callout_color: str = Config.DEFAULT_ELEVATION_CALLOUT_COLOR,
) -> Optional[str]:
    if not bid_conditions or not bid_takeoffs:
        return None
    processed_meshes, bounds = process_meshes_for_threejs(
        bid_conditions,
        bid_takeoffs,
        coord_system,
        color_service=color_service,
        takeoff_service=takeoff_service,
        display_mode=display_mode_3d,
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
    scene_data["display_modes"] = {
        "synced": bool(display_modes_synced),
        "mode_3d": display_mode_3d,
        "mode_2d": display_mode_2d,
    }
    page_entries, pdf_documents, takeoffs_2d, elevation_callouts = (
        _build_multi_page_data(
            pages or [],
            bid_conditions,
            bid_takeoffs,
            color_service,
            takeoff_service,
            display_mode_2d,
            grayscale_enabled,
            page_area_selections,
            include_elevation_callouts=include_elevation_callouts,
            elevation_callout_settings=elevation_callout_settings,
            elevation_callout_color=elevation_callout_color,
            page_floor_elevations=resolve_page_floor_elevations(
                (
                    str(metadata.get("page_uid", "") or ""),
                    (vertex[2] for vertex in mesh.vertices),
                )
                for mesh, metadata in processed_meshes
            ),
        )
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
        if elevation_callouts:
            scene_data["elevation_callouts"] = elevation_callouts
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
        webbrowser.open(Path(output_path).resolve().as_uri())
    return output_path


def _build_multi_page_data(
    pages: List[PageVisualizationPageDto],
    bid_conditions: Dict[str, Condition],
    bid_takeoffs: List[Takeoff],
    color_service: IColorService,
    takeoff_service: ITakeoffDomainService,
    display_mode: str,
    grayscale_enabled: bool,
    page_area_selections: Optional[Dict],
    *,
    include_elevation_callouts: bool,
    page_floor_elevations: Dict[str, float],
    elevation_callout_settings: ElevationCalloutSettings = (
        DEFAULT_ELEVATION_CALLOUT_SETTINGS
    ),
    elevation_callout_color: str = Config.DEFAULT_ELEVATION_CALLOUT_COLOR,
):
    page_entries = []
    takeoffs_2d = []
    elevation_callouts = []
    pdf_documents_by_source_page: Dict[Tuple[str, int], str] = {}
    pdf_documents = []
    takeoffs_by_page: Dict[str, List[Takeoff]] = {}
    for takeoff in bid_takeoffs:
        takeoffs_by_page.setdefault(takeoff.page_uid or "", []).append(takeoff)
    for page in pages:
        page_uid = str(page["uid"])
        pdf_document_uid = ""
        pdf_path = page.get("pdf_path")
        pdf_page_index = int(page["pdf_page_index"] or 0)
        if pdf_path and os.path.isfile(pdf_path):
            normalized_pdf_path = os.path.abspath(pdf_path)
            source_page_key = (normalized_pdf_path, pdf_page_index)
            pdf_document_uid = pdf_documents_by_source_page.get(source_page_key, "")
            if not pdf_document_uid:
                data_base64 = _extract_pdf_page_base64(
                    normalized_pdf_path, pdf_page_index
                )
                if data_base64:
                    pdf_document_uid = f"pdf-{len(pdf_documents) + 1}"
                    pdf_documents_by_source_page[source_page_key] = pdf_document_uid
                    pdf_documents.append(
                        {"uid": pdf_document_uid, "data_base64": data_base64}
                    )
        page_entry = {
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
            "pdf_page_index": pdf_page_index,
        }
        transform = None
        if page_uid in page_floor_elevations:
            transform = threejs_page_plane_transform(
                float(page["page_width"] or 0.0),
                float(page["page_height"] or 0.0),
                page_floor_elevations[page_uid],
            )
        if transform is not None:
            page_entry.update(
                {
                    "plane_x": transform.plane_x,
                    "plane_y": transform.plane_y,
                    "plane_z": transform.plane_z,
                    "plane_width": transform.plane_width,
                    "plane_height": transform.plane_height,
                    "plane_flip_u": transform.flip_u,
                    "plane_flip_v": transform.flip_v,
                }
            )
        page_entries.append(page_entry)
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
            page_takeoffs_2d, page_elevation_callouts = process_takeoffs_2d_for_threejs(
                bid_conditions,
                takeoffs_by_page.get(page_uid, []),
                color_service,
                takeoff_service,
                page_info,
                include_elevation_callouts=include_elevation_callouts,
                display_mode=display_mode,
                grayscale_enabled=grayscale_enabled,
                page_area_selections=page_area_selections,
                elevation_callout_settings=elevation_callout_settings,
                elevation_callout_color=elevation_callout_color,
            )
            takeoffs_2d.extend(page_takeoffs_2d)
            elevation_callouts.extend(page_elevation_callouts)
    return page_entries, pdf_documents, takeoffs_2d, elevation_callouts


def _extract_pdf_page_base64(pdf_path: str, page_index: int) -> str:
    output_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
            output_path = temp_pdf.name
        writer = ost_pdf_writer.PDFWriter()
        if not writer.copy_page(pdf_path, page_index, output_path):
            return ""
        with open(output_path, "rb") as extracted_pdf:
            return base64.b64encode(extracted_pdf.read()).decode("ascii")
    except OSError:
        return ""
    finally:
        if output_path:
            try:
                os.unlink(output_path)
            except OSError:
                pass


def _generate_html(scene_data: SceneData, title: str) -> str:
    template_path = Path(__file__).parent / "templates" / "viewer.html"
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()
    scene_json = json.dumps(scene_data, separators=(",", ":")).replace("<", "\\u003c")
    rendered_html = template.replace("{{TITLE}}", html.escape(title, quote=False))
    return rendered_html.replace("{{SCENE_DATA}}", scene_json)
