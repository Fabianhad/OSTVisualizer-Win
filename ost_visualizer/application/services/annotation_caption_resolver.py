from typing import Collection, Dict, List
from ...domain.entities.annotation_caption import (
    ANNOTATION_CAPTION_ORDER,
    AnnotationCaptionId,
)
from ...domain.entities.condition import Condition
from ...domain.entities.takeoff import Takeoff
from ...domain.services.uom_service import (
    CALC_AREA,
    CALC_AREA_PERIMETER,
    CALC_AREA_VOLUME,
    CALC_ALL_SIDES,
    CALC_LINEAR_BOTH_ENDS,
    CALC_LINEAR_BOTH_SIDES,
    CALC_LINEAR_LENGTH,
    CALC_TOP_BOTTOM,
    CALC_VOLUME,
    UOM_CUBIC_YARDS,
    UOM_EACH,
    UOM_LINEAR_FEET,
    UOM_SQUARE_FEET,
)
from ..dtos.annotation_caption_dto import (
    ANNOTATION_CAPTION_SPECS,
    AnnotationCaptionSettingsDto,
    ResolvedAnnotationCaptionDto,
)
from ..interfaces.i_uom_service import IUOMService


class AnnotationCaptionResolver:
    def __init__(self, uom_service: IUOMService):
        self._uom_service = uom_service

    def resolve(
        self,
        condition: Condition,
        takeoff: Takeoff,
        hole_positions: List[List[float]],
        settings: AnnotationCaptionSettingsDto,
        label: str,
    ) -> ResolvedAnnotationCaptionDto:
        if not settings.enabled:
            return ResolvedAnnotationCaptionDto()
        selected = settings.selected_ids
        values = self._resolve_values(
            condition,
            takeoff,
            hole_positions,
            selected,
            label,
        )
        selected_caption_ids = tuple(
            caption_id
            for caption_id in ANNOTATION_CAPTION_ORDER
            if caption_id in selected
        )
        applicable_caption_ids = [
            caption_id for caption_id in selected_caption_ids if caption_id in values
        ]
        expected_measurement_lines = sum(
            caption_id != AnnotationCaptionId.LABEL
            for caption_id in selected_caption_ids
        )
        if (
            AnnotationCaptionId.DEPTH in selected
            and AnnotationCaptionId.DEPTH not in values
        ):
            expected_measurement_lines -= 1
        lines = []
        for caption_id in applicable_caption_ids:
            spec = ANNOTATION_CAPTION_SPECS[caption_id]
            value = values[caption_id]
            if caption_id == AnnotationCaptionId.LABEL:
                text = value
            elif (
                caption_id == AnnotationCaptionId.AREA
                and expected_measurement_lines <= 1
            ):
                text = value
            else:
                text = f"{spec.prefix} = {value}"
            lines.append(text)
        measurement_types = 0
        for caption_id in selected_caption_ids:
            measurement_types |= ANNOTATION_CAPTION_SPECS[caption_id].measurement_type
        caption_label = label if AnnotationCaptionId.LABEL in selected and label else ""
        return ResolvedAnnotationCaptionDto(
            lines=tuple(lines),
            label=caption_label,
            measurement_types=measurement_types,
        )

    def _resolve_values(
        self,
        condition: Condition,
        takeoff: Takeoff,
        hole_positions: List[List[float]],
        selected: Collection[AnnotationCaptionId],
        label: str,
    ) -> Dict[AnnotationCaptionId, str]:
        values: Dict[AnnotationCaptionId, str] = {}
        if AnnotationCaptionId.LABEL in selected and label:
            values[AnnotationCaptionId.LABEL] = label
        if condition.is_area:
            self._resolve_area_values(
                values, condition, takeoff, hole_positions, selected
            )
        elif condition.is_linear:
            self._resolve_linear_values(values, condition, takeoff, selected)
        elif condition.is_count or condition.is_attachment:
            self._resolve_count_values(values, condition, takeoff, selected)
        self._resolve_slope(values, condition, selected)
        return values

    def _resolve_area_values(
        self,
        values: Dict[AnnotationCaptionId, str],
        condition: Condition,
        takeoff: Takeoff,
        hole_positions: List[List[float]],
        selected: Collection[AnnotationCaptionId],
    ) -> None:
        depth_inches = max(condition.thickness, 0.0)
        requests = []
        if AnnotationCaptionId.LENGTH in selected or (
            depth_inches > 0.0 and AnnotationCaptionId.WALL_AREA in selected
        ):
            requests.append(
                (AnnotationCaptionId.LENGTH, CALC_AREA_PERIMETER, UOM_LINEAR_FEET)
            )
        if AnnotationCaptionId.AREA in selected:
            requests.append((AnnotationCaptionId.AREA, CALC_AREA, UOM_SQUARE_FEET))
        if depth_inches > 0.0 and AnnotationCaptionId.VOLUME in selected:
            requests.append(
                (AnnotationCaptionId.VOLUME, CALC_AREA_VOLUME, UOM_CUBIC_YARDS)
            )
        quantities = self._calculate_caption_values(
            condition,
            takeoff,
            hole_positions,
            requests,
        )
        if AnnotationCaptionId.LENGTH in selected:
            values[AnnotationCaptionId.LENGTH] = self._format_distance_mm(
                quantities[AnnotationCaptionId.LENGTH] * 12.0
            )
        if AnnotationCaptionId.AREA in selected:
            values[AnnotationCaptionId.AREA] = self._format_decimal_unit(
                quantities[AnnotationCaptionId.AREA], "sf"
            )
        if depth_inches > 0.0:
            if AnnotationCaptionId.VOLUME in selected:
                values[AnnotationCaptionId.VOLUME] = self._format_reduced_decimal_unit(
                    quantities[AnnotationCaptionId.VOLUME], "cu yd"
                )
            if AnnotationCaptionId.DEPTH in selected:
                values[AnnotationCaptionId.DEPTH] = self._format_depth_inches(
                    depth_inches
                )
            if AnnotationCaptionId.WALL_AREA in selected:
                values[AnnotationCaptionId.WALL_AREA] = (
                    self._format_reduced_decimal_unit(
                        quantities[AnnotationCaptionId.LENGTH] * (depth_inches / 12.0),
                        "sf",
                    )
                )
        if (
            AnnotationCaptionId.WIDTH in selected
            or AnnotationCaptionId.HEIGHT in selected
        ):
            width_inches, height_inches = (
                self._uom_service.calculate_bounding_box_inches(takeoff.position)
            )
            if width_inches > 0.0 and AnnotationCaptionId.WIDTH in selected:
                values[AnnotationCaptionId.WIDTH] = self._format_distance_mm(
                    width_inches
                )
            if height_inches > 0.0 and AnnotationCaptionId.HEIGHT in selected:
                values[AnnotationCaptionId.HEIGHT] = self._format_distance_mm(
                    height_inches
                )

    def _resolve_linear_values(
        self,
        values: Dict[AnnotationCaptionId, str],
        condition: Condition,
        takeoff: Takeoff,
        selected: Collection[AnnotationCaptionId],
    ) -> None:
        depth_inches = max(condition.height, 0.0)
        requests = []
        if AnnotationCaptionId.LENGTH in selected:
            requests.append(
                (AnnotationCaptionId.LENGTH, CALC_LINEAR_LENGTH, UOM_LINEAR_FEET)
            )
        if AnnotationCaptionId.AREA in selected:
            requests.append(
                (AnnotationCaptionId.AREA, CALC_TOP_BOTTOM, UOM_SQUARE_FEET)
            )
        if depth_inches > 0.0 and AnnotationCaptionId.VOLUME in selected:
            requests.append((AnnotationCaptionId.VOLUME, CALC_VOLUME, UOM_CUBIC_YARDS))
        quantities = self._calculate_caption_values(
            condition,
            takeoff,
            [],
            requests,
        )
        if AnnotationCaptionId.LENGTH in selected:
            values[AnnotationCaptionId.LENGTH] = self._format_distance_mm(
                quantities[AnnotationCaptionId.LENGTH] * 12.0
            )
        if AnnotationCaptionId.AREA in selected:
            values[AnnotationCaptionId.AREA] = self._format_decimal_unit(
                quantities[AnnotationCaptionId.AREA], "sf"
            )
        if depth_inches > 0.0:
            if AnnotationCaptionId.VOLUME in selected:
                values[AnnotationCaptionId.VOLUME] = self._format_reduced_decimal_unit(
                    quantities[AnnotationCaptionId.VOLUME], "cu yd"
                )
            if AnnotationCaptionId.DEPTH in selected:
                values[AnnotationCaptionId.DEPTH] = self._format_depth_inches(
                    depth_inches
                )
            if AnnotationCaptionId.WALL_AREA in selected:
                both_sides_sf, both_ends_sf, _ = self._calculate(
                    condition,
                    takeoff,
                    [],
                    (CALC_LINEAR_BOTH_SIDES, CALC_LINEAR_BOTH_ENDS, 0),
                    (UOM_SQUARE_FEET, UOM_SQUARE_FEET, UOM_EACH),
                )
                values[AnnotationCaptionId.WALL_AREA] = (
                    self._format_reduced_decimal_unit(
                        both_sides_sf + both_ends_sf,
                        "sf",
                    )
                )
        if (
            AnnotationCaptionId.WIDTH in selected
            or AnnotationCaptionId.HEIGHT in selected
        ):
            width_inches, height_inches = (
                self._uom_service.calculate_bounding_box_inches(takeoff.position)
            )
            if width_inches > 0.0 and AnnotationCaptionId.WIDTH in selected:
                values[AnnotationCaptionId.WIDTH] = self._format_distance_mm(
                    width_inches
                )
            footprint_height = max(condition.thickness, height_inches)
            if footprint_height > 0.0 and AnnotationCaptionId.HEIGHT in selected:
                values[AnnotationCaptionId.HEIGHT] = self._format_distance_mm(
                    footprint_height
                )

    def _resolve_count_values(
        self,
        values: Dict[AnnotationCaptionId, str],
        condition: Condition,
        takeoff: Takeoff,
        selected: Collection[AnnotationCaptionId],
    ) -> None:
        depth_inches = max(condition.height, 0.0)
        requests = []
        if AnnotationCaptionId.AREA in selected:
            requests.append(
                (AnnotationCaptionId.AREA, CALC_TOP_BOTTOM, UOM_SQUARE_FEET)
            )
        if depth_inches > 0.0 and AnnotationCaptionId.VOLUME in selected:
            requests.append((AnnotationCaptionId.VOLUME, CALC_VOLUME, UOM_CUBIC_YARDS))
        if depth_inches > 0.0 and AnnotationCaptionId.WALL_AREA in selected:
            requests.append(
                (AnnotationCaptionId.WALL_AREA, CALC_ALL_SIDES, UOM_SQUARE_FEET)
            )
        quantities = self._calculate_caption_values(
            condition,
            takeoff,
            [],
            requests,
        )
        if AnnotationCaptionId.AREA in selected:
            values[AnnotationCaptionId.AREA] = self._format_decimal_unit(
                quantities[AnnotationCaptionId.AREA], "sf"
            )
        if depth_inches > 0.0:
            if AnnotationCaptionId.VOLUME in selected:
                values[AnnotationCaptionId.VOLUME] = self._format_reduced_decimal_unit(
                    quantities[AnnotationCaptionId.VOLUME], "cu yd"
                )
            if AnnotationCaptionId.DEPTH in selected:
                values[AnnotationCaptionId.DEPTH] = self._format_depth_inches(
                    depth_inches
                )
        width_inches = max(condition.width, 0.0)
        height_inches = max(condition.depth, 0.0)
        if width_inches > 0.0 and AnnotationCaptionId.WIDTH in selected:
            values[AnnotationCaptionId.WIDTH] = self._format_distance_mm(width_inches)
        if height_inches > 0.0 and AnnotationCaptionId.HEIGHT in selected:
            values[AnnotationCaptionId.HEIGHT] = self._format_distance_mm(height_inches)
        if depth_inches > 0.0 and AnnotationCaptionId.WALL_AREA in selected:
            wall_area_sf = quantities[AnnotationCaptionId.WALL_AREA]
            if wall_area_sf > 0.0:
                values[AnnotationCaptionId.WALL_AREA] = (
                    self._format_reduced_decimal_unit(wall_area_sf, "sf")
                )

    def _calculate_caption_values(
        self,
        condition: Condition,
        takeoff: Takeoff,
        hole_positions: List[List[float]],
        requests: List[tuple[AnnotationCaptionId, int, int]],
    ) -> Dict[AnnotationCaptionId, float]:
        if not requests:
            return {}
        calculation_requests = [
            (calc_type, uom) for _caption_id, calc_type, uom in requests
        ]
        calculation_requests.extend(
            (0, UOM_EACH) for _ in range(3 - len(calculation_requests))
        )
        results = self._calculate(
            condition,
            takeoff,
            hole_positions,
            tuple(request[0] for request in calculation_requests),
            tuple(request[1] for request in calculation_requests),
        )
        return {request[0]: results[index] for index, request in enumerate(requests)}

    def _calculate(
        self,
        condition: Condition,
        takeoff: Takeoff,
        hole_positions: List[List[float]],
        calc_types: tuple[int, int, int],
        uoms: tuple[int, int, int],
    ) -> tuple[float, float, float]:
        return self._uom_service.calculate_condition_quantities(
            condition_type=condition.condition_type,
            calc_type1=calc_types[0],
            calc_type2=calc_types[1],
            calc_type3=calc_types[2],
            uom1=uoms[0],
            uom2=uoms[1],
            uom3=uoms[2],
            width=condition.width,
            height=condition.height,
            depth=condition.depth,
            thickness=condition.thickness,
            position=takeoff.position,
            hole_positions=hole_positions,
            rise=condition.rise,
            run=condition.run,
            grid_size1=condition.grid_size1,
            grid_size2=condition.grid_size2,
            gap=condition.gap,
            curve=takeoff.curve,
            round_quantity=False,
            round_up=0.0,
        )

    @staticmethod
    def _resolve_slope(
        values: Dict[AnnotationCaptionId, str],
        condition: Condition,
        selected: Collection[AnnotationCaptionId],
    ) -> None:
        rise = condition.rise
        run = condition.run
        if (
            AnnotationCaptionId.SLOPE in selected
            and (condition.is_area or condition.is_linear)
            and rise > 0.0
            and run > 0.0
        ):
            values[AnnotationCaptionId.SLOPE] = (
                f"{AnnotationCaptionResolver._format_compact(rise)}/"
                f"{AnnotationCaptionResolver._format_compact(run)} Pitch"
            )

    @staticmethod
    def _format_decimal_unit(value: float, unit: str) -> str:
        return f"{value:,.2f} {unit}"

    @staticmethod
    def _format_reduced_decimal_unit(value: float, unit: str) -> str:
        formatted = f"{value:,.2f}".rstrip("0").rstrip(".")
        return f"{formatted} {unit}"

    @staticmethod
    def _format_compact(value: float) -> str:
        return f"{value:.2f}".rstrip("0").rstrip(".")

    @staticmethod
    def _format_depth_inches(value: float) -> str:
        quarter_inches = round(value * 4.0)
        feet, quarter_remainder = divmod(quarter_inches, 48)
        inches, fraction_numerator = divmod(quarter_remainder, 4)
        fraction = ("", " 1/4", " 1/2", " 3/4")[fraction_numerator]
        inch_text = f'{inches}{fraction}"'
        if feet:
            return f"{feet}' - {inch_text}"
        return inch_text

    @staticmethod
    def _format_distance_mm(value_inches: float) -> str:
        return f"{value_inches * 25.4:,.2f} mm"
