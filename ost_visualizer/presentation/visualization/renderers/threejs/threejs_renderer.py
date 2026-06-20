import base64
import json
import os
import tempfile
import time
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional
from .....application.dtos.scene_data_dto import SceneData
from .....application.interfaces.i_color_service import IColorService
from .....application.interfaces.i_coordinate_transformer import ICoordinateTransformer
from .....application.interfaces.i_takeoff_domain_service import ITakeoffDomainService
from .....domain.entities.config import Config
from .....domain.entities.condition import Condition
from .....domain.entities.takeoff import Takeoff
from .adapters.threejs_mesh_adapter import ThreejsMeshAdapter
from .mesh_processor import process_meshes_for_threejs


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
    pdf_path: Optional[str] = None,
    pdf_page_index: int = 0,
    page_width_inches: float = 0.0,
    page_height_inches: float = 0.0,
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
    )
    if not processed_meshes:
        return None
    adapter = ThreejsMeshAdapter(color_service)
    scene_data = adapter.build_scene_data(processed_meshes, bounds, title)
    if pdf_path and os.path.isfile(pdf_path):
        try:
            with open(pdf_path, "rb") as pf:
                scene_data["pdf_base64"] = base64.b64encode(pf.read()).decode("ascii")
            scene_data["pdf_page_index"] = pdf_page_index
            if page_width_inches > 0 and page_height_inches > 0:
                scene_data["page_width"] = page_width_inches
                scene_data["page_height"] = page_height_inches
        except OSError:
            pass
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


def _generate_html(scene_data: SceneData, title: str) -> str:
    template_path = Path(__file__).parent / "templates" / "viewer.html"
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()
    scene_json = json.dumps(scene_data, separators=(",", ":"))
    html = template.replace("{{TITLE}}", title)
    html = html.replace("{{SCENE_DATA}}", scene_json)
    return html
