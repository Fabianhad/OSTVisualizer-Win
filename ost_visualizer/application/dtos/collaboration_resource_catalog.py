from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import hashlib
from types import MappingProxyType
from typing import Collection, Iterable, Mapping, Optional


class CollaborationResourceType(str, Enum):
    DATABASE = "database"
    PROJECT = "project"
    PROJECTS_COLLECTION = "projects_collection"
    PROJECT_BIDS = "project_bids"
    BID = "bid"
    CONDITION = "condition"
    CONDITION_FOLDER = "condition_folder"
    CONDITIONS_COLLECTION = "conditions_collection"
    AREA = "area"
    AREAS_COLLECTION = "areas_collection"
    PAGE = "page"
    PAGES_COLLECTION = "pages_collection"
    LAYER = "layer"
    LAYERS_COLLECTION = "layers_collection"
    DEFAULT_LAYERS_COLLECTION = "default_layers_collection"
    TAKEOFF = "takeoff"
    TAKEOFFS_COLLECTION = "takeoffs_collection"
    ANNOTATION = "annotation"
    ANNOTATIONS_COLLECTION = "annotations_collection"
    COVER_SHEET = "cover_sheet"
    JOB_STATUS = "job_status"
    JOB_STATUSES_COLLECTION = "job_statuses_collection"
    EMPLOYEE = "employee"
    EMPLOYEES_COLLECTION = "employees_collection"
    PAY_CLASS = "pay_class"
    PAY_CLASSES_COLLECTION = "pay_classes_collection"
    CONDITION_TYPE = "condition_type"
    CONDITION_TYPES_COLLECTION = "condition_types_collection"


class CollaborationResourceFamily(str, Enum):
    HIERARCHY = "hierarchy"
    CONDITIONS = "conditions"
    AREAS = "areas"
    TAKEOFFS = "takeoffs"
    ANNOTATIONS = "annotations"
    PAGES = "pages"
    LAYERS = "layers"
    COVER_SHEET = "cover_sheet"
    MASTER_DATA = "master_data"


@dataclass(frozen=True)
class CollaborationResourceDefinition:
    resource_type: CollaborationResourceType
    family: CollaborationResourceFamily
    collection: bool = False
    bid_scoped: bool = False
    entity_table: str = ""
    entity_uid_column: str = "UID"
    entity_bid_column: str = ""
    seed_filter: str = ""
    coalesce_type: Optional[CollaborationResourceType] = None
    reconciliation_supported: bool = True


_DEFINITIONS = (
    CollaborationResourceDefinition(
        CollaborationResourceType.DATABASE,
        CollaborationResourceFamily.HIERARCHY,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.PROJECT,
        CollaborationResourceFamily.HIERARCHY,
        entity_table="BidProjects",
        coalesce_type=CollaborationResourceType.PROJECTS_COLLECTION,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.PROJECTS_COLLECTION,
        CollaborationResourceFamily.HIERARCHY,
        collection=True,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.PROJECT_BIDS,
        CollaborationResourceFamily.HIERARCHY,
        collection=True,
        coalesce_type=CollaborationResourceType.PROJECTS_COLLECTION,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.BID,
        CollaborationResourceFamily.HIERARCHY,
        bid_scoped=True,
        entity_table="Bids",
        entity_bid_column="UID",
        coalesce_type=CollaborationResourceType.PROJECTS_COLLECTION,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.CONDITION,
        CollaborationResourceFamily.CONDITIONS,
        bid_scoped=True,
        entity_table="BidConditions",
        entity_bid_column="BidUID",
        coalesce_type=CollaborationResourceType.CONDITIONS_COLLECTION,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.CONDITION_FOLDER,
        CollaborationResourceFamily.CONDITIONS,
        bid_scoped=True,
        entity_table="BidConditionFolders",
        entity_bid_column="BidUID",
        coalesce_type=CollaborationResourceType.CONDITIONS_COLLECTION,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.CONDITIONS_COLLECTION,
        CollaborationResourceFamily.CONDITIONS,
        collection=True,
        bid_scoped=True,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.AREA,
        CollaborationResourceFamily.AREAS,
        bid_scoped=True,
        entity_table="BidAreas",
        entity_bid_column="BidUID",
        coalesce_type=CollaborationResourceType.AREAS_COLLECTION,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.AREAS_COLLECTION,
        CollaborationResourceFamily.AREAS,
        collection=True,
        bid_scoped=True,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.PAGE,
        CollaborationResourceFamily.PAGES,
        bid_scoped=True,
        entity_table="BidPages",
        entity_bid_column="BidUID",
        coalesce_type=CollaborationResourceType.PAGES_COLLECTION,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.PAGES_COLLECTION,
        CollaborationResourceFamily.PAGES,
        collection=True,
        bid_scoped=True,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.LAYER,
        CollaborationResourceFamily.LAYERS,
        bid_scoped=True,
        entity_table="BidLayers",
        entity_bid_column="BidUID",
        seed_filter="[IsTemplate]=0",
        coalesce_type=CollaborationResourceType.LAYERS_COLLECTION,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.LAYERS_COLLECTION,
        CollaborationResourceFamily.LAYERS,
        collection=True,
        bid_scoped=True,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.DEFAULT_LAYERS_COLLECTION,
        CollaborationResourceFamily.LAYERS,
        collection=True,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.TAKEOFF,
        CollaborationResourceFamily.TAKEOFFS,
        bid_scoped=True,
        entity_table="BidTakeoffs",
        entity_bid_column="BidUID",
        coalesce_type=CollaborationResourceType.TAKEOFFS_COLLECTION,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.TAKEOFFS_COLLECTION,
        CollaborationResourceFamily.TAKEOFFS,
        collection=True,
        bid_scoped=True,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.ANNOTATION,
        CollaborationResourceFamily.ANNOTATIONS,
        bid_scoped=True,
        coalesce_type=CollaborationResourceType.ANNOTATIONS_COLLECTION,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.ANNOTATIONS_COLLECTION,
        CollaborationResourceFamily.ANNOTATIONS,
        collection=True,
        bid_scoped=True,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.COVER_SHEET,
        CollaborationResourceFamily.COVER_SHEET,
        bid_scoped=True,
        entity_table="Bids",
        entity_bid_column="UID",
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.JOB_STATUS,
        CollaborationResourceFamily.MASTER_DATA,
        entity_table="JobStatuses",
        coalesce_type=CollaborationResourceType.JOB_STATUSES_COLLECTION,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.JOB_STATUSES_COLLECTION,
        CollaborationResourceFamily.MASTER_DATA,
        collection=True,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.EMPLOYEE,
        CollaborationResourceFamily.MASTER_DATA,
        entity_table="Employees",
        coalesce_type=CollaborationResourceType.EMPLOYEES_COLLECTION,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.EMPLOYEES_COLLECTION,
        CollaborationResourceFamily.MASTER_DATA,
        collection=True,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.PAY_CLASS,
        CollaborationResourceFamily.MASTER_DATA,
        entity_table="PayClasses",
        coalesce_type=CollaborationResourceType.PAY_CLASSES_COLLECTION,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.PAY_CLASSES_COLLECTION,
        CollaborationResourceFamily.MASTER_DATA,
        collection=True,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.CONDITION_TYPE,
        CollaborationResourceFamily.HIERARCHY,
        entity_table="CdnTypes",
        coalesce_type=CollaborationResourceType.CONDITION_TYPES_COLLECTION,
    ),
    CollaborationResourceDefinition(
        CollaborationResourceType.CONDITION_TYPES_COLLECTION,
        CollaborationResourceFamily.HIERARCHY,
        collection=True,
    ),
)
COLLABORATION_RESOURCE_CATALOG = MappingProxyType(
    {definition.resource_type.value: definition for definition in _DEFINITIONS}
)


def resource_definition(resource_type: str) -> CollaborationResourceDefinition:
    try:
        return COLLABORATION_RESOURCE_CATALOG[resource_type]
    except KeyError as exc:
        raise ValueError(
            f"Unknown collaboration resource type: {resource_type}"
        ) from exc


def resource_types_for_family(
    family: CollaborationResourceFamily,
) -> frozenset[str]:
    return frozenset(
        name
        for name, definition in COLLABORATION_RESOURCE_CATALOG.items()
        if definition.family == family
    )


def coalesced_resource_type(resource_type: str) -> str:
    definition = resource_definition(resource_type)
    return (definition.coalesce_type or definition.resource_type).value


def parse_annotation_resource_id(resource_id: str) -> tuple[str, str]:
    annotation_type, separator, annotation_uid = str(resource_id).partition("/")
    if not separator or not annotation_type or not annotation_uid:
        raise ValueError("Invalid annotation collaboration resource identity")
    return annotation_type, annotation_uid


def annotation_resource_id(annotation_type: str, annotation_uid: str) -> str:
    normalized_type = str(annotation_type or "")
    normalized_uid = str(annotation_uid or "")
    if not normalized_type or not normalized_uid:
        raise ValueError("Invalid annotation collaboration resource identity")
    return f"{normalized_type}/{normalized_uid}"


def resource_families_affect_page(
    families: Iterable[str],
    affected_page_uids_by_family: Mapping[str, Collection[str]],
    page_uid: str,
) -> bool:
    normalized_page_uid = str(page_uid or "")
    for family in families:
        affected_page_uids = affected_page_uids_by_family.get(family)
        if affected_page_uids is None:
            return True
        if normalized_page_uid in {
            str(affected_page_uid) for affected_page_uid in affected_page_uids
        }:
            return True
    return False


SUPPORTED_REMOTE_RESOURCE_TYPES = frozenset(
    name
    for name, definition in COLLABORATION_RESOURCE_CATALOG.items()
    if definition.reconciliation_supported
)
CONDITION_RESOURCE_TYPES = resource_types_for_family(
    CollaborationResourceFamily.CONDITIONS
)
AREA_RESOURCE_TYPES = resource_types_for_family(CollaborationResourceFamily.AREAS)
HIERARCHY_RESOURCE_TYPES = resource_types_for_family(
    CollaborationResourceFamily.HIERARCHY
)
MASTER_DATA_RESOURCE_TYPES = resource_types_for_family(
    CollaborationResourceFamily.MASTER_DATA
)
BID_CONTENT_FAMILY_BY_RESOURCE_TYPE = MappingProxyType(
    {
        name: definition.family.value
        for name, definition in COLLABORATION_RESOURCE_CATALOG.items()
        if definition.bid_scoped
        and definition.family
        in {
            CollaborationResourceFamily.TAKEOFFS,
            CollaborationResourceFamily.ANNOTATIONS,
            CollaborationResourceFamily.PAGES,
            CollaborationResourceFamily.LAYERS,
        }
    }
)
BID_CONTENT_RESOURCE_TYPES = frozenset(BID_CONTENT_FAMILY_BY_RESOURCE_TYPE)
BID_CONTENT_ENTITY_RESOURCE_TYPES = frozenset(
    name
    for name in BID_CONTENT_RESOURCE_TYPES
    if not COLLABORATION_RESOURCE_CATALOG[name].collection
)


def _catalog_checksum() -> str:
    rows = (
        "|".join(
            (
                name,
                definition.family.value,
                "collection" if definition.collection else "entity",
                "bid" if definition.bid_scoped else "database",
                definition.entity_table,
                definition.entity_uid_column,
                definition.entity_bid_column,
                definition.seed_filter,
                (
                    definition.coalesce_type.value
                    if definition.coalesce_type is not None
                    else ""
                ),
                (
                    "reconcile"
                    if definition.reconciliation_supported
                    else "controlled_reload"
                ),
            )
        )
        for name, definition in sorted(COLLABORATION_RESOURCE_CATALOG.items())
    )
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


COLLABORATION_RESOURCE_CATALOG_CHECKSUM = _catalog_checksum()
