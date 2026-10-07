import logging
import uuid
from typing import Callable, Dict, Optional, Tuple
from ...application.dtos.ai_changeset_write_dtos import (
    AiChangesetCommit,
    AiChangesetUndoPlan,
    AiChangesetWritePlan,
    AiChangesetWriteResult,
    AiScaleUndoPlan,
    AiTakeoffWrite,
    AppliedChangeset,
)
from ...application.dtos.collaboration_dtos import (
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ...application.dtos.create_condition_spec_dto import CreateConditionSpec
from ...domain.entities.ai_changeset import (
    ERROR_INVALID_STATE,
    ERROR_SQL_APPLY_UNAVAILABLE,
    ERROR_STALE_CHANGESET,
    EXISTING_CONDITION_PREFIX,
    KIND_SCALE,
    STATUS_APPLIED,
    AiChangeset,
    ChangesetError,
    resolved_condition_name,
)
from ...domain.entities.ai_takeoff import Assumption, SidecarWriteRefused
from ...domain.entities.condition import Condition
from ...domain.services.uom_service import (
    CALC_AREA,
    CALC_AREA_VOLUME,
    UOM_CUBIC_YARDS,
    UOM_SQUARE_FEET,
)
from .ai_changeset_approval import ApplyOutcome
from .undo_redo_service import UndoRedoService

logger = logging.getLogger(__name__)
ERROR_FEATURE_DENIED = "feature_denied"
ERROR_LOCKED_BID = "locked_bid"
ERROR_LEASE_CONFLICT = "lease_conflict"
ERROR_APPLY_FAILED = "apply_failed"
AI_SLAB_COLOR = 33023
_COMMITTED = {
    MutationOutcomeStatus.COMMITTED,
    MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
}
Done = Callable[[ApplyOutcome], None]


class AiChangesetApplier:
    def __init__(
        self,
        write_service,
        project_data,
        undo_service: UndoRedoService,
        store,
        token_reader,
        access_check: Callable[[AiChangeset], str],
        layer_uid: Callable[[], Optional[str]],
        area_uid: Callable[[str], Optional[str]],
        session_folder_name: str,
        audit: Callable[[str, dict], None] = lambda _event, _details: None,
        record_assumptions: Callable[
            [Tuple[Assumption, ...]], None
        ] = lambda _items: None,
        apply_blocked: Callable[[str], str] = lambda _database_id: "",
    ):
        self._write = write_service
        self._project = project_data
        self._undo_service = undo_service
        self._store = store
        self._tokens = token_reader
        self._access_check = access_check
        self._layer_uid = layer_uid
        self._area_uid = area_uid
        self._session_folder_name = session_folder_name
        self._audit = audit
        self._record_assumptions = record_assumptions
        self._apply_blocked = apply_blocked
        self._session_folders: Dict[Tuple[str, str], str] = {}
        self._undo_entries: Dict[str, object] = {}

    def apply(self, changeset: AiChangeset, done: Done) -> None:
        blocked = self._apply_blocked(changeset.database_id)
        if blocked:
            done(ApplyOutcome(False, None, blocked, ERROR_SQL_APPLY_UNAVAILABLE))
            return
        denial = self._access_check(changeset)
        if denial:
            done(ApplyOutcome(False, None, denial, ERROR_FEATURE_DENIED))
            return
        try:
            if changeset.kind == KIND_SCALE:
                self._apply_scale(changeset, done)
            else:
                self._apply_elements(changeset, done)
        except ChangesetError as exc:
            done(ApplyOutcome(False, None, exc.message, exc.code))

    def undo(self, uid: str, done: Done) -> None:
        try:
            changeset = self._store.get(uid)
        except ChangesetError as exc:
            done(ApplyOutcome(False, None, exc.message, exc.code))
            return
        blocked = self._apply_blocked(changeset.database_id)
        if blocked:
            done(ApplyOutcome(False, None, blocked, ERROR_SQL_APPLY_UNAVAILABLE))
            return
        record = self._store.applied_record(uid)
        if changeset.status != STATUS_APPLIED or record is None:
            done(
                ApplyOutcome(
                    False,
                    None,
                    f"The changeset is {changeset.status} and cannot be undone.",
                    ERROR_INVALID_STATE,
                )
            )
            return
        resources = tuple(resource for resource, _token in record.resulting_tokens)
        current = self._tokens(changeset.database_id, changeset.bid_uid, resources)
        if {resource: current.get(resource, "") for resource in resources} != dict(
            record.resulting_tokens
        ):
            done(
                ApplyOutcome(
                    False,
                    None,
                    "Something this changeset created was edited since. Undo it by hand.",
                    ERROR_STALE_CHANGESET,
                )
            )
            return
        denial = self._access_check(changeset)
        if denial:
            done(ApplyOutcome(False, None, denial, ERROR_FEATURE_DENIED))
            return

        def finished(commit: AiChangesetCommit) -> None:
            if not commit.committed:
                done(self._failure(commit))
                return
            self._store.mark_undone(uid)
            entry = self._undo_entries.pop(uid, None)
            if entry is not None:
                self._undo_service.discard_entry(entry)
            self._audit("undone", {"changeset_id": uid})
            done(ApplyOutcome(True, record))

        if changeset.kind == KIND_SCALE:
            self._run_scale_undo(changeset, record, finished)
        else:
            self._run_elements_undo(changeset, record, finished)

    def _apply_elements(self, changeset: AiChangeset, done: Done) -> None:
        conditions = changeset.resolved_conditions()
        key = (changeset.database_id, str(changeset.bid_uid))
        folder_uid = self._session_folders.get(key)
        if (
            folder_uid is not None
            and folder_uid not in self._project.get_bid_condition_folders()
        ):
            folder_uid = None
        layer_uid = self._layer_uid()
        existing = tuple(
            dict.fromkeys(
                takeoff.condition_key[len(EXISTING_CONDITION_PREFIX) :]
                for takeoff in changeset.takeoffs
                if takeoff.condition_key.startswith(EXISTING_CONDITION_PREFIX)
            )
        )
        plan = AiChangesetWritePlan(
            folder_name=self._session_folder_name,
            existing_folder_uid=folder_uid,
            conditions=tuple(
                (condition.key, self._slab_spec(condition, layer_uid))
                for condition in conditions
            ),
            takeoffs=tuple(
                AiTakeoffWrite(
                    condition_key=(
                        takeoff.condition_key[len(EXISTING_CONDITION_PREFIX) :]
                        if takeoff.condition_key.startswith(EXISTING_CONDITION_PREFIX)
                        else takeoff.condition_key
                    ),
                    page_uid=takeoff.page_uid,
                    position=tuple(takeoff.polygon),
                    holes=tuple(tuple(hole) for hole in takeoff.holes),
                    area_uid=self._area_uid(takeoff.page_uid),
                )
                for takeoff in changeset.takeoffs
            ),
            existing_condition_uids=existing,
        )

        def finished(commit: AiChangesetCommit) -> None:
            if not commit.committed or commit.result is None:
                done(self._failure(commit))
                return
            result = commit.result
            if result.folder_uid:
                self._session_folders[key] = result.folder_uid
            resources = tuple(
                [f"takeoff:{uid}" for uid in result.takeoff_uids]
                + [f"condition:{uid}" for _key, uid in result.condition_uids]
                + [f"condition_takeoffs:{uid}" for _key, uid in result.condition_uids]
            )
            record = AppliedChangeset(
                folder_uid=result.folder_uid,
                created_folder=result.created_folder,
                condition_uids=tuple(uid for _key, uid in result.condition_uids),
                takeoff_uids=tuple(result.takeoff_uids),
                resulting_tokens=self._read_tokens(changeset, resources),
            )
            self._push_undo(changeset, f"AI: {changeset.summary or 'takeoffs'}")
            self._persist_assumptions(changeset)
            self._audit(
                "applied",
                {
                    "changeset_id": changeset.uid,
                    "takeoffs": len(record.takeoff_uids),
                    "conditions": len(record.condition_uids),
                },
            )
            done(ApplyOutcome(True, record))

        if self._write.uses_sql_collaboration_mutations(changeset.database_id):
            self._write.queue_ai_changeset(
                changeset.database_id,
                str(changeset.bid_uid),
                plan,
                lambda result: finished(_commit_from_queue(result)),
            )
            return
        finished(
            self._write.execute_ai_changeset_local(
                changeset.database_id, str(changeset.bid_uid), plan
            )
        )

    def _apply_scale(self, changeset: AiChangeset, done: Done) -> None:
        scale = changeset.resolved_scale()
        positions = tuple(
            (str(takeoff.uid), tuple(float(value) for value in takeoff.position))
            for takeoff in self._project.get_page_takeoffs(scale.page_uid)
        )

        def finished(success: bool, message: str = "", conflict: bool = False) -> None:
            if not success:
                locked = bool(self._project.is_current_bid_locked())
                done(
                    self._failure(
                        AiChangesetCommit(
                            False,
                            message=message
                            or (
                                "The bid is locked."
                                if locked
                                else "The scale was not saved."
                            ),
                            locked=locked,
                            conflict=conflict,
                        )
                    )
                )
                return
            record = AppliedChangeset(
                page_uid=scale.page_uid,
                previous_scale=(scale.previous_sf1, scale.previous_sf2),
                previous_positions=positions,
                resulting_tokens=self._read_tokens(
                    changeset,
                    (f"page:{scale.page_uid}", f"page_takeoffs:{scale.page_uid}"),
                ),
            )
            self._push_undo(changeset, f"AI: page scale {scale.sf1:g} : {scale.sf2:g}")
            self._persist_assumptions(changeset)
            self._audit(
                "applied",
                {"changeset_id": changeset.uid, "scale": [scale.sf1, scale.sf2]},
            )
            done(ApplyOutcome(True, record))

        if self._write.uses_sql_collaboration_mutations(changeset.database_id):
            self._write.queue_page_setting_if_sql(
                changeset.database_id,
                scale.page_uid,
                "scale",
                [scale.sf1, scale.sf2],
                owning_surface="ai-takeoff",
                callback=lambda result: finished(
                    result.outcome_status in _COMMITTED,
                    result.message,
                    result.conflict is not None,
                ),
            )
            return
        finished(
            bool(
                self._write.save_page_scale(
                    changeset.database_id, scale.page_uid, scale.sf1, scale.sf2
                )
            )
        )

    def _run_elements_undo(
        self,
        changeset: AiChangeset,
        record: AppliedChangeset,
        finished: Callable[[AiChangesetCommit], None],
    ) -> None:
        folder_uid = None
        if record.created_folder and record.folder_uid:
            others = [
                condition
                for condition in self._project.get_bid_conditions().values()
                if condition.folder_uid == record.folder_uid
                and condition.uid not in record.condition_uids
            ]
            if not others:
                folder_uid = record.folder_uid
        plan = AiChangesetUndoPlan(
            record.takeoff_uids, record.condition_uids, folder_uid
        )
        if self._write.uses_sql_collaboration_mutations(changeset.database_id):
            self._write.queue_ai_changeset_undo(
                changeset.database_id,
                str(changeset.bid_uid),
                plan,
                lambda result: finished(_commit_from_queue(result)),
            )
            return
        finished(
            self._write.execute_ai_changeset_undo_local(
                changeset.database_id, str(changeset.bid_uid), plan
            )
        )

    def _run_scale_undo(
        self,
        changeset: AiChangeset,
        record: AppliedChangeset,
        finished: Callable[[AiChangesetCommit], None],
    ) -> None:
        previous = record.previous_scale or (0.0, 0.0)
        plan = AiScaleUndoPlan(
            record.page_uid or "", previous[0], previous[1], record.previous_positions
        )
        if self._write.uses_sql_collaboration_mutations(changeset.database_id):
            self._write.queue_page_setting_if_sql(
                changeset.database_id,
                plan.page_uid,
                "scale",
                [plan.scale_factor1, plan.scale_factor2],
                owning_surface="ai-takeoff",
                callback=lambda result: finished(_commit_from_queue(result)),
            )
            return
        finished(
            self._write.execute_ai_scale_undo_local(
                changeset.database_id, str(changeset.bid_uid), plan
            )
        )

    def _persist_assumptions(self, changeset: AiChangeset) -> None:
        if not changeset.assumptions:
            return
        items = tuple(
            Assumption(
                uid=f"{changeset.uid}-{item.uid}",
                value=str(
                    item.effective_value
                    if item.effective_value is not None
                    else item.value
                ),
                reason=item.reason,
                sheet_ref=item.sheet_ref,
                impact=item.impact,
                status=item.status,
            )
            for item in changeset.assumptions
        )
        try:
            self._record_assumptions(items)
        except SidecarWriteRefused as exc:
            self._audit("sidecar_refused", {"status": exc.status})
        except (OSError, ValueError) as exc:
            logger.warning("AI assumptions were not saved: %s", type(exc).__name__)
            self._audit("sidecar_failed", {"error": type(exc).__name__})

    def _push_undo(self, changeset: AiChangeset, label: str) -> None:
        uid = changeset.uid

        def undo_submit(complete: Callable[[QueuedMutationResult], None]) -> None:
            self.undo(
                uid,
                lambda outcome: complete(
                    _queued_result(
                        changeset.database_id, outcome.success, outcome.message
                    )
                ),
            )

        def redo_submit(complete: Callable[[QueuedMutationResult], None]) -> None:
            complete(
                _queued_result(
                    changeset.database_id,
                    False,
                    "AI changesets cannot be redone. Ask the AI to propose it again.",
                )
            )

        bid_ref = self._project.get_current_bid_ref()
        if bid_ref is None:
            return
        entry = self._undo_service.push_for_bid(
            bid_ref, undo_submit, redo_submit, label=label
        )
        if entry is not None:
            self._undo_entries[uid] = entry

    def _read_tokens(
        self, changeset: AiChangeset, resources
    ) -> Tuple[Tuple[str, str], ...]:
        tokens = self._tokens(
            changeset.database_id, changeset.bid_uid, tuple(resources)
        )
        return tuple(
            (resource, str(tokens.get(resource, ""))) for resource in resources
        )

    @staticmethod
    def _slab_spec(condition, layer_uid: Optional[str]) -> CreateConditionSpec:
        return CreateConditionSpec(
            name=resolved_condition_name(condition),
            condition_type=Condition.TYPE_AREA,
            thickness=float(condition.thickness_in),
            layer_uid=layer_uid,
            color_fill=AI_SLAB_COLOR,
            calc_type1=CALC_AREA,
            uom1=UOM_SQUARE_FEET,
            calc_type2=CALC_AREA_VOLUME,
            uom2=UOM_CUBIC_YARDS,
            uom3=-1,
        )

    @staticmethod
    def _failure(commit: AiChangesetCommit) -> ApplyOutcome:
        if commit.locked:
            code = ERROR_LOCKED_BID
        elif commit.conflict:
            code = ERROR_LEASE_CONFLICT
        else:
            code = ERROR_APPLY_FAILED
        return ApplyOutcome(
            False, None, commit.message or "The change was not saved.", code
        )


def _commit_from_queue(result: QueuedMutationResult) -> AiChangesetCommit:
    if result.outcome_status not in _COMMITTED:
        return AiChangesetCommit(
            False,
            message=result.message,
            locked=result.rejection_reason is not None,
            conflict=result.conflict is not None,
        )
    maps = (
        dict(result.authoritative_result.created_uid_maps)
        if result.authoritative_result
        else {}
    )
    folder_map = dict(maps.get("condition_folders", ()))
    takeoffs = dict(maps.get("takeoffs", ()))
    return AiChangesetCommit(
        True,
        AiChangesetWriteResult(
            folder_uid=folder_map.get("0"),
            created_folder="0" in folder_map,
            condition_uids=tuple(maps.get("conditions", ())),
            takeoff_uids=tuple(takeoffs[str(index)] for index in range(len(takeoffs))),
        ),
    )


def _queued_result(
    database_id: str, success: bool, message: str
) -> QueuedMutationResult:
    return QueuedMutationResult(
        database_id=database_id,
        runtime_generation=0,
        operation_id=str(uuid.uuid4()),
        outcome_status=(
            MutationOutcomeStatus.COMMITTED
            if success
            else MutationOutcomeStatus.REJECTED
        ),
        message="" if success else message,
        commit_attempted=success,
    )
