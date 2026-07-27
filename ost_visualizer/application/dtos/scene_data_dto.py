from typing import List, TypedDict


class SceneCameraConfig(TypedDict):
    position: List[float]
    target: List[float]


class SceneBoundsConfig(TypedDict):
    min: List[float]
    max: List[float]


class SceneDisplayModesConfig(TypedDict):
    synced: bool
    mode_3d: str
    mode_2d: str


class SceneGeometryEntry(TypedDict):
    vertices: List[float]
    normals: List[float]
    indices: List[int]
    color: List[float]
    opacity: float
    name: str
    visible: bool
    takeoff_uid: str
    page_uid: str
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


class ScenePdfDocumentEntry(TypedDict):
    uid: str
    data_base64: str


class _ScenePagePlaneEntry(TypedDict, total=False):
    plane_x: float
    plane_y: float
    plane_z: float
    plane_width: float
    plane_height: float
    plane_flip_u: bool
    plane_flip_v: bool


class ScenePageEntry(_ScenePagePlaneEntry):
    uid: str
    label: str
    name: str
    sheet_no: str
    sequence: int
    width: float
    height: float
    page_width: float
    page_height: float
    image_layer_uid: str
    visible: bool
    pdf_document_uid: str
    pdf_page_index: int


class SceneTakeoff2DEntry(TypedDict):
    takeoff_uid: str
    page_uid: str
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


class SceneElevationCalloutEntry(TypedDict):
    page_uid: str
    condition_uid: str
    area_uid: str
    layer_uid: str
    x: float
    y: float
    lines: List[str]
    color: str


class _OptionalSceneData(TypedDict, total=False):
    layers: List[SceneLayerEntry]
    conditions: List[SceneConditionEntry]
    areas: List[SceneAreaEntry]
    page_image_layer: ScenePageImageLayer
    pages: List[ScenePageEntry]
    active_page_uid: str
    selected_page_uids: List[str]
    pdf_documents: List[ScenePdfDocumentEntry]
    takeoffs_2d: List[SceneTakeoff2DEntry]
    elevation_callouts: List[SceneElevationCalloutEntry]
    display_modes: SceneDisplayModesConfig


class SceneData(_OptionalSceneData):
    title: str
    geometries: List[SceneGeometryEntry]
    camera: SceneCameraConfig
    bounds: SceneBoundsConfig
