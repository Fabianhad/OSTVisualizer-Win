from __future__ import annotations
import logging
from typing import Dict, Optional
from ....domain.entities.condition import Condition
from ...dtos.update_condition_dto import UpdateConditionDto, UpdateConditionResultDto
from ...interfaces.i_mdb_writer import IMdbWriter


class UpdateConditionUseCase:
    def __init__(
        self, mdb_writer: IMdbWriter, logger: Optional[logging.Logger] = None
    ) -> None:
        self._writer = mdb_writer
        self.logger = logger or logging.getLogger(__name__)

    def execute(
        self,
        db_path: str,
        bid_uid: str,
        condition_uid: str,
        updates: UpdateConditionDto,
        all_conditions: Optional[Dict[str, Condition]] = None,
    ) -> UpdateConditionResultDto:
        changes = updates.get_changes()
        if not changes:
            return UpdateConditionResultDto(success=True)
        if "name" in changes:
            name = changes["name"]
            if not name or not name.strip():
                return UpdateConditionResultDto(
                    success=False, error="Condition name cannot be empty."
                )
        if "display_size" in changes:
            ds = changes["display_size"]
            if ds < 10 or ds > 500:
                return UpdateConditionResultDto(
                    success=False,
                    error="Display Size must be between 10% and 500%.",
                )
        if "ref_no" in changes and all_conditions:
            new_ref = changes["ref_no"]
            original = all_conditions.get(condition_uid)
            old_ref = original.ref_no if original else None
            if new_ref != old_ref:
                has_conflict = any(
                    c.ref_no == new_ref
                    for uid, c in all_conditions.items()
                    if uid != condition_uid
                )
                if has_conflict:
                    self._writer.shift_ref_nos(db_path, bid_uid, new_ref, condition_uid)
        ok = self._writer.update_condition(db_path, bid_uid, condition_uid, updates)
        if not ok:
            return UpdateConditionResultDto(
                success=False, error="Failed to save condition to database."
            )
        return UpdateConditionResultDto(success=True)
