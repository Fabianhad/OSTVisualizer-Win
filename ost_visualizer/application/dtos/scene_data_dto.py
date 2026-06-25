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
    visible: bool
    takeoff_uid: str
    condition_uid: str
    area_uid: str
    layer_uid: str
    cdn_type_uid: str
    cdn_type_name: str


class SceneLayerEntry(TypedDict):
    uid: str
    name: str
    visible: bool
    sequence: int


class SceneConditionEntry(TypedDict):
    uid: str
    name: str
    layer_uid: str
    visible: bool
    cdn_type_uid: str
    cdn_type_name: str
    color: str
    ref_no: int


class SceneAreaEntry(TypedDict):
    uid: str
    name: str
    visible: bool
    sequence: int


class ScenePageImageLayer(TypedDict):
    uid: str
    name: str
    visible: bool


class ScenePage2DEntry(TypedDict):
    uid: str
    width: float
    height: float
    image_layer_uid: str
    visible: bool


class SceneTakeoff2DEntry(TypedDict):
    takeoff_uid: str
    condition_uid: str
    area_uid: str
    layer_uid: str
    name: str
    visible: bool
    kind: str
    color: str
    opacity: float
    rings: List[List[List[float]]]
    is_negative: bool


class SceneData(TypedDict, total=False):
    title: str
    geometries: List[SceneGeometryEntry]
    camera: SceneCameraConfig
    bounds: SceneBoundsConfig
    layers: List[SceneLayerEntry]
    conditions: List[SceneConditionEntry]
    areas: List[SceneAreaEntry]
    page_image_layer: ScenePageImageLayer
    page_2d: ScenePage2DEntry
    takeoffs_2d: List[SceneTakeoff2DEntry]
    pdf_base64: str
    pdf_page_index: int
    page_width: float
    page_height: float
