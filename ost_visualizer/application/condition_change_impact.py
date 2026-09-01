from collections.abc import Iterable
from .dtos.collaboration_dtos import ChangeOperation

_MESH_FIELDS = frozenset(
    {
        "color_fill",
        "condition_type",
        "depth",
        "display_size",
        "drop_run",
        "drop_value",
        "height",
        "is_top",
        "layer_uid",
        "pattern",
        "rise",
        "run",
        "shape",
        "thickness",
        "width",
        "z_value",
    }
)
_NON_MESH_FIELDS = frozenset(
    {
        "backout",
        "calc_type1",
        "calc_type2",
        "calc_type3",
        "cdn_type_uid",
        "condition_folder",
        "condition_type_catalog",
        "display_dimension",
        "display_grid_while_drawing",
        "display_name",
        "folder_uid",
        "gap",
        "grid",
        "grid_size1",
        "grid_size2",
        "is_curved_segment",
        "name",
        "notes",
        "ref_no",
        "round_quantity",
        "round_up",
        "spacing",
        "trim",
        "uom1",
        "uom2",
        "uom3",
    }
)
_NON_PLAN_FIELDS = frozenset(
    {
        "cdn_type_uid",
        "condition_folder",
        "condition_type_catalog",
        "folder_uid",
        "notes",
        "ref_no",
    }
)


def condition_changes_require_mesh_refresh(
    changed_fields: Iterable[str],
    change_operations: Iterable[str] = (),
) -> bool:
    fields = {str(field) for field in changed_fields if field}
    operations = {str(operation) for operation in change_operations if operation}
    if ChangeOperation.DELETE.value in operations:
        return True
    unknown_fields = fields.difference(_MESH_FIELDS, _NON_MESH_FIELDS)
    if fields:
        return bool(fields.intersection(_MESH_FIELDS) or unknown_fields)
    return not operations or not operations.issubset(
        {ChangeOperation.CREATE.value, ChangeOperation.REORDER.value}
    )


def condition_changes_require_plan_refresh(
    changed_fields: Iterable[str],
    change_operations: Iterable[str] = (),
) -> bool:
    fields = {str(field) for field in changed_fields if field}
    operations = {str(operation) for operation in change_operations if operation}
    if ChangeOperation.DELETE.value in operations:
        return True
    if ChangeOperation.CREATE.value in operations:
        return True
    if fields:
        return bool(fields.difference(_NON_PLAN_FIELDS))
    return not operations or not operations.issubset({ChangeOperation.REORDER.value})
