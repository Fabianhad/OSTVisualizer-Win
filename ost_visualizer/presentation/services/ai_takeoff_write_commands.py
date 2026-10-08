from typing import Callable, Dict, List
from ...application.dtos.ai_takeoff_dtos import (
    COMMAND_APPLY_CHANGESET,
    COMMAND_DISCARD_CHANGESET,
    COMMAND_FIND_REGIONS,
    COMMAND_PROPOSE_ELEMENT,
    COMMAND_PROPOSE_SCALE,
    COMMAND_RENDER_3D,
    COMMAND_UNDO_LAST_AI_CHANGESET,
    COMMAND_UPDATE_ASSUMPTION,
    ERROR_BID_NOT_OPEN,
    ERROR_INVALID_ARGUMENT,
    ERROR_NOT_FOUND,
    AiTakeoffRequestError,
    error_result,
    ok_result,
)
from ...domain.entities.ai_changeset import (
    ERROR_INVALID_STATE,
    STATUS_PENDING_APPROVAL,
    STATUS_UNDONE,
    ChangesetError,
)

UNDO_STATUS_UNDONE = "undone"
UNDO_STATUS_ALREADY_UNDONE = "already_undone"


class DeferredReply:
    def __init__(self):
        self._callback = None
        self._result = None
        self._resolved = False

    def attach(self, callback: Callable[[dict], None]) -> None:
        if self._resolved:
            callback(self._result)
            return
        self._callback = callback

    def resolve(self, result: dict) -> None:
        if self._resolved:
            return
        self._resolved = True
        self._result = result
        if self._callback is not None:
            self._callback(result)


class AiTakeoffWriteCommands:
    def __init__(
        self,
        read_service,
        proposal_service,
        proposals,
        undo: Callable,
        top_view,
        apply_requested: Callable[[str], None],
    ):
        self._read = read_service
        self._proposal = proposal_service
        self._proposals = proposals
        self._undo = undo
        self._top_view = top_view
        self._apply_requested = apply_requested
        self._undoing: Dict[str, List[DeferredReply]] = {}

    def handlers(self) -> Dict[str, Callable[[dict], object]]:
        return {
            COMMAND_PROPOSE_SCALE: self._propose_scale,
            COMMAND_FIND_REGIONS: self._find_regions,
            COMMAND_PROPOSE_ELEMENT: self._propose_element,
            COMMAND_APPLY_CHANGESET: self._apply_changeset,
            COMMAND_DISCARD_CHANGESET: self._discard_changeset,
            COMMAND_UNDO_LAST_AI_CHANGESET: self._undo_last,
            COMMAND_RENDER_3D: self._render_3d,
            COMMAND_UPDATE_ASSUMPTION: self._update_assumption,
        }

    def _propose_scale(self, arguments: dict) -> dict:
        return self._proposal.propose_scale(
            arguments.get("page_uid"),
            arguments.get("p1_pts"),
            arguments.get("p2_pts"),
            real_in=arguments.get("real_in"),
            preset=arguments.get("preset"),
            reason=arguments.get("reason"),
            sheet_ref=arguments.get("sheet_ref"),
        )

    def _find_regions(self, arguments: dict) -> Callable[[], dict]:
        snapshot = self._read.page_snapshot(arguments.get("page_uid"))
        proposal = self._proposal
        return lambda: proposal.find_regions(
            snapshot,
            arguments.get("bbox_pts"),
            gap_close_in=arguments.get("gap_close_in"),
            seed_pts=arguments.get("seed_pts"),
        )

    def _propose_element(self, arguments: dict) -> dict:
        return self._proposal.propose_element(
            arguments.get("kind"),
            arguments.get("page_uid"),
            polygon_ost=arguments.get("polygon_ost"),
            region_id=arguments.get("region_id"),
            holes_ost=arguments.get("holes_ost"),
            thickness_in=arguments.get("thickness_in"),
            top_elev_in=arguments.get("top_elev_in"),
            level_id=arguments.get("level_id"),
            name=arguments.get("name"),
            summary=arguments.get("summary"),
            condition_uid=arguments.get("condition_uid"),
        )

    def _apply_changeset(self, arguments: dict) -> dict:
        result = self._proposal.apply_changeset(arguments.get("changeset_id"))
        if result.get("status") == STATUS_PENDING_APPROVAL:
            self._apply_requested(result["data"]["changeset_id"])
        return result

    def _discard_changeset(self, arguments: dict) -> dict:
        return self._proposal.discard_changeset(arguments.get("changeset_id"))

    def _update_assumption(self, arguments: dict) -> dict:
        return self._proposal.update_assumption(
            arguments.get("changeset_id"),
            arguments.get("op"),
            assumption_id=arguments.get("assumption_id"),
            subject=arguments.get("subject"),
            target_key=arguments.get("target_key"),
            value=arguments.get("value"),
            reason=arguments.get("reason"),
            sheet_ref=arguments.get("sheet_ref"),
            length_in=arguments.get("length_in"),
        )

    def _undo_last(self, arguments: dict):
        bid_ref = self._open_bid(arguments.get("bid_uid"))
        uid = arguments.get("changeset_id")
        if not isinstance(uid, str) or not uid.strip():
            raise AiTakeoffRequestError(
                ERROR_INVALID_ARGUMENT, "changeset_id must name the changeset to undo"
            )
        waiting = self._undoing.get(uid)
        if waiting is not None:
            reply = DeferredReply()
            waiting.append(reply)
            return reply
        try:
            changeset = self._proposals.get(uid)
        except ChangesetError as exc:
            raise AiTakeoffRequestError(exc.code, exc.message) from exc
        if str(changeset.database_id) != str(bid_ref.file_path) or str(
            changeset.bid_uid
        ) != str(bid_ref.bid_uid):
            raise AiTakeoffRequestError(
                ERROR_NOT_FOUND, "That changeset does not belong to the open bid"
            )
        if changeset.status == STATUS_UNDONE:
            return _already_undone(uid)
        last = self._proposals.last_applied(
            str(bid_ref.file_path), str(bid_ref.bid_uid)
        )
        if last is None or last.uid != uid:
            raise AiTakeoffRequestError(
                ERROR_INVALID_STATE,
                "Only the most recent applied AI changeset of the open bid can be undone",
            )
        reply = DeferredReply()
        waiting = [reply]
        self._undoing[uid] = waiting

        def done(outcome) -> None:
            self._undoing.pop(uid, None)
            if outcome.success:
                waiting[0].resolve(
                    ok_result({"changeset_id": uid, "status": UNDO_STATUS_UNDONE})
                )
                for other in waiting[1:]:
                    other.resolve(_already_undone(uid))
                return
            failure = error_result(outcome.code or "undo_failed", outcome.message)
            for each in waiting:
                each.resolve(failure)

        self._undo(uid, done)
        return reply

    def _render_3d(self, arguments: dict) -> Callable[[], dict]:
        self._open_bid(arguments.get("bid_uid"))
        if arguments.get("view", "top") != "top":
            raise AiTakeoffRequestError(
                ERROR_INVALID_ARGUMENT, "Only view=top is available"
            )
        snapshot = self._top_view.snapshot()
        top_view = self._top_view

        def render() -> dict:
            data = top_view.render(snapshot)
            return ok_result(data, "ok" if data.get("image") else "empty")

        return render

    def _open_bid(self, bid_uid):
        bid_ref = self._read.open_bid_ref()
        if bid_uid is not None and str(bid_uid) != str(bid_ref.bid_uid):
            raise AiTakeoffRequestError(
                ERROR_BID_NOT_OPEN, "Only the bid open in OST Visualizer can be used."
            )
        return bid_ref


def _already_undone(uid: str) -> dict:
    return ok_result(
        {"changeset_id": uid, "status": UNDO_STATUS_ALREADY_UNDONE},
        UNDO_STATUS_ALREADY_UNDONE,
    )
