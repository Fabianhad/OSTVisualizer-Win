from typing import List, TypedDict


class SceneCameraConfig(TypedDict):
    position: List[float]
    target: List[float]


class SceneBoundsConfig(TypedDict):
    min: List[float]
    max: List[float]


class SceneGeometryEntry(TypedDict):
    vertices: List[float]
    normals: List[float]
    indices: List[int]
    color: List[float]
    opacity: float
    name: str


class SceneData(TypedDict, total=False):
    title: str
    geometries: List[SceneGeometryEntry]
    camera: SceneCameraConfig
    bounds: SceneBoundsConfig
    pdf_base64: str
    pdf_page_index: int
    page_width: float
    page_height: float
