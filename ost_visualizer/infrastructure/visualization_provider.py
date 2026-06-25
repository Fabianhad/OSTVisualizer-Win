from typing import Dict, List, Optional, Sequence, Tuple, Union
from ..application.dtos.html_export_page_dto import HtmlExportPageDto
from ..application.dtos.mesh_geometry_dto import MeshGeometry
from ..application.dtos.scene_data_dto import ScenePageImageLayer
from ..application.interfaces.i_color_service import IColorService
from ..application.interfaces.i_coordinate_transformer_factory import (
    ICoordinateTransformerFactory,
)
from ..application.interfaces.i_exporter import IExportStrategy
from ..application.interfaces.i_html_renderer import IHtmlRenderer
from ..application.interfaces.i_mesh_generator import IMeshGenerator, MeshData
from ..application.interfaces.i_takeoff_domain_service import ITakeoffDomainService
from ..application.interfaces.i_visualization_provider import (
    Bounds,
    IVisualizationProvider,
)
from ..domain.entities.area import BidArea
from ..domain.entities.layer import BidLayer
from ..presentation.visualization.exporters.dxf_exporter import DXFExporter
from ..presentation.visualization.exporters.fbx_exporter import FBXExporter
from ..presentation.visualization.exporters.obj_exporter import OBJExporter
from ..presentation.visualization.factories.coordinate_transformer_factory import (
    CoordinateTransformerFactory,
)
from ..presentation.visualization.meshing.mesh_builder import process_takeoffs_to_meshes
from ..presentation.visualization.renderers.threejs.threejs_renderer import (
    visualize_with_threejs,
)
from ..presentation.visualization.services.color_service import ColorService
from ..presentation.visualization.utils.mesh import meshes_to_geometries
from .utils.filename import sanitize_filename


class _MeshGeneratorAdapter(IMeshGenerator):
    def __init__(
        self,
        coord_factory: ICoordinateTransformerFactory,
        color_service: IColorService,
        takeoff_service: ITakeoffDomainService,
    ):
        self._coord_factory = coord_factory
        self._color_service = color_service
        self._takeoff_service = takeoff_service

    def generate_meshes(
        self,
        bid_conditions: Dict,
        bid_takeoffs: List,
        page_area_selections: Optional[Dict] = None,
        color_mode: str = "Solid",
        grayscale_enabled: bool = True,
    ):
        coord_system = self._coord_factory.create()
        meshes, mesh_colors, bounds = process_takeoffs_to_meshes(
            bid_conditions,
            bid_takeoffs,
            coord_system,
            color_service=self._color_service,
            takeoff_service=self._takeoff_service,
            page_area_selections=page_area_selections,
            color_mode=color_mode,
            grayscale_enabled=grayscale_enabled,
        )
        return meshes, mesh_colors, bounds


class _HtmlRendererAdapter(IHtmlRenderer):
    def __init__(
        self,
        coord_factory: ICoordinateTransformerFactory,
        color_service: IColorService,
        takeoff_service: ITakeoffDomainService,
    ):
        self._coord_factory = coord_factory
        self._color_service = color_service
        self._takeoff_service = takeoff_service

    def render(
        self,
        bid_conditions: Dict,
        bid_takeoffs: List,
        output_path: str,
        title: str = "3D Visualization",
        bid_name: str = "Bid",
        color_mode: str = "Solid",
        grayscale_enabled: bool = True,
        page_area_selections: Optional[Dict] = None,
        auto_open: bool = False,
        pages: Optional[List[HtmlExportPageDto]] = None,
        active_page_uid: str = "",
        layers: Optional[List[BidLayer]] = None,
        areas: Optional[List[BidArea]] = None,
        page_image_layer: Optional[ScenePageImageLayer] = None,
    ) -> bool:
        try:
            coord_system = self._coord_factory.create()
            visualize_with_threejs(
                bid_conditions,
                bid_takeoffs,
                coord_system,
                self._color_service,
                self._takeoff_service,
                title=title,
                output_path=output_path,
                auto_open=auto_open,
                bid_name=bid_name,
                color_mode=color_mode,
                grayscale_enabled=grayscale_enabled,
                page_area_selections=page_area_selections,
                pages=pages,
                active_page_uid=active_page_uid,
                layers=layers,
                areas=areas,
                page_image_layer=page_image_layer,
            )
            return True
        except Exception:
            return False


class _ExportStrategyAdapter(IExportStrategy):
    MAX_FILENAME_LENGTH = 255

    def __init__(
        self,
        name: str,
        extension: str,
        exporter_class: type,
        coord_factory: ICoordinateTransformerFactory,
        color_service: IColorService,
        takeoff_service: ITakeoffDomainService,
    ):
        self._name = name
        self._extension = extension
        self._exporter_class = exporter_class
        self._coord_factory = coord_factory
        self._color_service = color_service
        self._takeoff_service = takeoff_service

    @property
    def name(self) -> str:
        return self._name

    @property
    def extension(self) -> str:
        return self._extension

    def get_dialog_title(self, page_count: int) -> str:
        if page_count == 1:
            return f"Export page as {self._name}"
        return f"Export {page_count} pages as {self._name}"

    def prepare_filename(self, bid_name: str, page_names: List[str]) -> str:
        if len(page_names) == 1:
            clean_name = self._clean_filename(page_names[0])
            filename = f"{bid_name} - {clean_name}.{self._extension}"
        elif len(page_names) == 2:
            clean_names = [self._clean_filename(name) for name in page_names]
            filename = (
                f"{bid_name} - {clean_names[0]} + {clean_names[1]}.{self._extension}"
            )
        else:
            clean_names = [self._clean_filename(name) for name in page_names]
            first_page = clean_names[0]
            second_page = clean_names[1]
            remaining = len(clean_names) - 2
            filename = f"{bid_name} - {first_page} + {second_page} + {remaining} more.{self._extension}"
        if len(filename) > self.MAX_FILENAME_LENGTH:
            overflow = len(filename) - self.MAX_FILENAME_LENGTH
            max_project_length = len(bid_name) - overflow - 3
            if max_project_length > 10:
                truncated_project = bid_name[:max_project_length] + "..."
                filename = filename.replace(bid_name, truncated_project, 1)
            else:
                if len(page_names) == 1:
                    filename = f"{clean_names[0]}.{self._extension}"
                else:
                    filename = f"Export_{len(page_names)}_pages.{self._extension}"
        return filename

    def prepare_title(self, bid_name: str, page_names: List[str]) -> Optional[str]:
        return None

    def get_kwargs(self, config_model, page_area_selections=None):
        kwargs = {
            "color_mode": config_model.color_mode,
            "grayscale_enabled": config_model.grayscale_enabled,
        }
        if page_area_selections is not None:
            kwargs["page_area_selections"] = page_area_selections
        return kwargs

    def execute_export(
        self, bid_conditions: Dict, takeoffs: List, output_path: str, **kwargs
    ) -> bool:
        coord_system = self._coord_factory.create()
        exporter = self._exporter_class(
            coord_system, self._color_service, self._takeoff_service
        )
        try:
            result = exporter.export(bid_conditions, takeoffs, output_path, **kwargs)
            return result
        finally:
            del exporter

    @staticmethod
    def _clean_filename(filename: str) -> str:
        return sanitize_filename(filename)


class _HtmlExportStrategyAdapter(IExportStrategy):
    MAX_FILENAME_LENGTH = 255

    def __init__(self, html_renderer: IHtmlRenderer):
        self._name = "HTML"
        self._extension = "html"
        self._html_renderer = html_renderer

    @property
    def name(self) -> str:
        return self._name

    @property
    def extension(self) -> str:
        return self._extension

    def get_dialog_title(self, page_count: int) -> str:
        if page_count == 1:
            return f"Export page as {self._name}"
        return f"Export {page_count} pages as {self._name}"

    def prepare_filename(self, bid_name: str, page_names: List[str]) -> str:
        if len(page_names) == 1:
            clean_name = sanitize_filename(page_names[0])
            filename = f"{bid_name} - {clean_name}.{self._extension}"
        elif len(page_names) == 2:
            clean_names = [sanitize_filename(name) for name in page_names]
            filename = (
                f"{bid_name} - {clean_names[0]} + {clean_names[1]}.{self._extension}"
            )
        else:
            clean_names = [sanitize_filename(name) for name in page_names]
            first_page = clean_names[0]
            second_page = clean_names[1]
            remaining = len(clean_names) - 2
            filename = f"{bid_name} - {first_page} + {second_page} + {remaining} more.{self._extension}"
        if len(filename) > self.MAX_FILENAME_LENGTH:
            overflow = len(filename) - self.MAX_FILENAME_LENGTH
            max_project_length = len(bid_name) - overflow - 3
            if max_project_length > 10:
                truncated_project = bid_name[:max_project_length] + "..."
                filename = filename.replace(bid_name, truncated_project, 1)
            else:
                if len(page_names) == 1:
                    filename = f"{clean_names[0]}.{self._extension}"
                else:
                    filename = f"Export_{len(page_names)}_pages.{self._extension}"
        return filename

    def get_kwargs(self, config_model, page_area_selections=None):
        kwargs = {
            "color_mode": config_model.color_mode,
            "grayscale_enabled": config_model.grayscale_enabled,
        }
        if page_area_selections is not None:
            kwargs["page_area_selections"] = page_area_selections
        return kwargs

    def prepare_title(self, bid_name: str, page_names: List[str]) -> str:
        if len(page_names) == 1:
            return f"{bid_name} - {page_names[0]}"
        if len(page_names) == 2:
            return f"{bid_name} - {page_names[0]} + {page_names[1]}"
        first_page = page_names[0]
        second_page = page_names[1]
        remaining = len(page_names) - 2
        return f"{bid_name} - {first_page} + {second_page} + {remaining} more"

    def execute_export(
        self, bid_conditions: Dict, takeoffs: List, output_path: str, **kwargs
    ) -> bool:
        exportable_takeoffs = [
            t
            for t in takeoffs
            if (c_uid := t.condition_uid) in bid_conditions
            and bid_conditions[c_uid].condition_type in [0, 1, 2, 3]
        ]
        if not exportable_takeoffs:
            return False
        return self._html_renderer.render(
            bid_conditions,
            exportable_takeoffs,
            output_path,
            title=kwargs.get("title", "3D View"),
            bid_name=kwargs.get("bid_name", "Bid"),
            color_mode=kwargs.get("color_mode", "Solid"),
            grayscale_enabled=kwargs.get("grayscale_enabled", True),
            page_area_selections=kwargs.get("page_area_selections"),
            auto_open=False,
            pages=kwargs.get("pages"),
            active_page_uid=kwargs.get("active_page_uid", ""),
            layers=kwargs.get("layers"),
            areas=kwargs.get("areas"),
            page_image_layer=kwargs.get("page_image_layer"),
        )


class VisualizationProvider(IVisualizationProvider):
    def __init__(self, takeoff_service: ITakeoffDomainService):
        self._coord_factory: ICoordinateTransformerFactory = (
            CoordinateTransformerFactory()
        )
        self._color_service: IColorService = ColorService()
        self._mesh_generator = _MeshGeneratorAdapter(
            self._coord_factory, self._color_service, takeoff_service
        )
        self._html_renderer = _HtmlRendererAdapter(
            self._coord_factory, self._color_service, takeoff_service
        )
        self._strategies: Dict[str, IExportStrategy] = {
            "obj": _ExportStrategyAdapter(
                "OBJ",
                "obj",
                OBJExporter,
                self._coord_factory,
                self._color_service,
                takeoff_service,
            ),
            "dxf": _ExportStrategyAdapter(
                "DXF",
                "dxf",
                DXFExporter,
                self._coord_factory,
                self._color_service,
                takeoff_service,
            ),
            "fbx": _ExportStrategyAdapter(
                "FBX",
                "fbx",
                FBXExporter,
                self._coord_factory,
                self._color_service,
                takeoff_service,
            ),
            "html": _HtmlExportStrategyAdapter(self._html_renderer),
        }

    def get_mesh_generator(self) -> IMeshGenerator:
        return self._mesh_generator

    def get_export_strategy(self, format_key: str) -> Optional[IExportStrategy]:
        return self._strategies.get(format_key)

    def get_available_formats(self) -> list[str]:
        return list(self._strategies.keys())

    def convert_meshes_to_geometries(
        self,
        meshes: Sequence[MeshData],
        mesh_colors: Dict[str, Union[str, Dict[str, object]]],
    ) -> Tuple[List[MeshGeometry], Bounds]:
        return meshes_to_geometries(meshes, mesh_colors, self._color_service)
