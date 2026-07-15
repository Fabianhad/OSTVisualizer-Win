from typing import List, NotRequired, TypedDict


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


class ScenePageEntry(TypedDict):
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
    plane_x: NotRequired[float]
    plane_y: NotRequired[float]
    plane_z: NotRequired[float]
    plane_width: NotRequired[float]
    plane_height: NotRequired[float]
    plane_flip_u: NotRequired[bool]
    plane_flip_v: NotRequired[bool]


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
    takeoff_uid: str
    page_uid: str
    condition_uid: str
    area_uid: str
    layer_uid: str
    visible: bool
    x: float
    y: float
    condition_label: str
    top_label: str
    bottom_label: str
    quantity_label: str


class SceneData(TypedDict, total=False):
    title: str
    geometries: List[SceneGeometryEntry]
    camera: SceneCameraConfig
    bounds: SceneBoundsConfig
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
