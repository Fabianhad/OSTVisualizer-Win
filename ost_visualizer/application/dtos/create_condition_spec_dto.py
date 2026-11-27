from dataclasses import asdict, dataclass, fields
from math import isfinite
from typing import Optional
from ...shared.texts import (
    CREATE_CONDITION_SPEC_DTO_LABEL_UNTITLED,
    CREATE_CONDITION_SPEC_DTO_MESSAGE_CONDITION_NAME_CANNOT_BE_EMPTY,
    CREATE_CONDITION_SPEC_DTO_MESSAGE_THE_CONDITION_WAS_NOT_CREATED_BECAUSE,
)


class InvalidConditionSpecError(ValueError):
    """A new condition whose name or numbers cannot be stored."""


@dataclass
class CreateConditionSpec:
    name: str = CREATE_CONDITION_SPEC_DTO_LABEL_UNTITLED
    condition_type: int = 0
    backout: bool = False
    cdn_type_uid: Optional[str] = None
    layer_uid: Optional[str] = None
    height: float = 0.0
    width: float = 12.0
    depth: float = 0.0
    thickness: float = 4.0
    rise: float = 0.0
    run: float = 0.0
    display_size: float = 100.0
    shape: int = -1
    pattern: int = 0
    spacing: float = 4.0
    color_fill: int = 0
    uom1: int = 0
    uom2: int = -1
    uom3: int = -1
    calc_type1: int = 0
    calc_type2: int = 0
    calc_type3: int = 0
    notes: str = ""
    drop_run: bool = False
    drop_value: float = 0.0
    round_quantity: bool = False
    round_up: float = 0.0
    trim: bool = False
    is_curved_segment: bool = False
    grid: bool = False
    grid_size1: float = 0.0
    grid_size2: float = 0.0
    gap: float = 0.0
    display_dimension: bool = False
    display_name: bool = False
    display_grid_while_drawing: bool = False
    folder_uid: Optional[str] = None


_FLOAT_FIELDS = frozenset(
    spec_field.name
    for spec_field in fields(CreateConditionSpec)
    if spec_field.type is float
)


def require_valid_create_condition_spec(spec: CreateConditionSpec) -> None:
    if not str(spec.name or "").strip():
        raise InvalidConditionSpecError(
            CREATE_CONDITION_SPEC_DTO_MESSAGE_CONDITION_NAME_CANNOT_BE_EMPTY
        )
    for name, value in asdict(spec).items():
        if name in _FLOAT_FIELDS and not isfinite(float(value)):
            raise InvalidConditionSpecError(
                CREATE_CONDITION_SPEC_DTO_MESSAGE_THE_CONDITION_WAS_NOT_CREATED_BECAUSE
            )
