from __future__ import annotations
import logging
from typing import Optional
from ...dtos.update_condition_dto import (
    ConditionNumberOverflowError,
    UpdateConditionDto,
    UpdateConditionResultDto,
)
from ...interfaces.i_mdb_writer import IMdbWriter
from ....shared.texts import (
    UPDATE_CONDITION_USE_CASE_MESSAGE_CONDITION_NAME_CANNOT_BE_EMPTY,
    UPDATE_CONDITION_USE_CASE_MESSAGE_DISPLAY_SIZE_MUST_BE_BETWEEN_10,
    UPDATE_CONDITION_USE_CASE_MESSAGE_FAILED_TO_SAVE_CONDITION_TO_DATABASE,
)


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
    ) -> UpdateConditionResultDto:
        changes = updates.get_changes()
        if not changes:
            return UpdateConditionResultDto(success=True)
        if "name" in changes:
            name = changes["name"]
            if not name or not name.strip():
                return UpdateConditionResultDto(
                    success=False,
                    error=UPDATE_CONDITION_USE_CASE_MESSAGE_CONDITION_NAME_CANNOT_BE_EMPTY,
                )
        if "display_size" in changes:
            ds = changes["display_size"]
            if ds < 10 or ds > 500:
                return UpdateConditionResultDto(
                    success=False,
                    error=UPDATE_CONDITION_USE_CASE_MESSAGE_DISPLAY_SIZE_MUST_BE_BETWEEN_10,
                )
        try:
            ok = self._writer.update_condition(db_path, bid_uid, condition_uid, updates)
        except ConditionNumberOverflowError as exc:
            return UpdateConditionResultDto(success=False, error=str(exc))
        if not ok:
            return UpdateConditionResultDto(
                success=False,
                error=UPDATE_CONDITION_USE_CASE_MESSAGE_FAILED_TO_SAVE_CONDITION_TO_DATABASE,
            )
        return UpdateConditionResultDto(success=True)
