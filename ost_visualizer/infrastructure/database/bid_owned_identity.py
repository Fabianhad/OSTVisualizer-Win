from __future__ import annotations
from collections.abc import Iterable, Iterator, Sequence
from ...application.dtos.collaboration_dtos import PlanTakeoffOwnership
from .schema_inspector_contract import IDatabaseSchemaInspector
from ...shared.texts import (
    BID_OWNED_IDENTITY_MESSAGE_A_TAKEOFF_AND_ITS_PARENT_MUST,
    BID_OWNED_IDENTITY_MESSAGE_CONTAINS_DUPLICATE_UID_AUTHORITATIVE_BID_OWNED,
    BID_OWNED_IDENTITY_MESSAGE_CONTAINS_MALFORMED_UID_AUTHORITATIVE_BID_OWNED,
    BID_OWNED_IDENTITY_MESSAGE_HAS_NO_ROW_FOR_UID_THE,
    BID_OWNED_IDENTITY_MESSAGE_MUTATION_REQUIRES_AT_LEAST_ONE_AUTHORITATIVE,
    BID_OWNED_IDENTITY_MESSAGE_MUTATION_TARGETS_DO_NOT_BELONG_TO,
    BID_OWNED_IDENTITY_MESSAGE_THE_PLAN_OWNERSHIP_SNAPSHOT_MUST_COVER,
    BID_OWNED_IDENTITY_MESSAGE_THE_TAKEOFF_OWNERSHIP_CHANGED_BEFORE_THE,
)

BID_OWNED_IDENTITY_QUERY_CHUNK_SIZE = 50


def _iter_uid_query_chunks(
    uid_ints: Sequence[int],
    chunk_size: int = BID_OWNED_IDENTITY_QUERY_CHUNK_SIZE,
) -> Iterator[list[int]]:
    for start in range(0, len(uid_ints), chunk_size):
        yield list(uid_ints[start : start + chunk_size])


def _fetch_uid_rows(cursor, table: str, columns: str, uid_ints: Sequence[int]):
    rows = []
    for uid_chunk in _iter_uid_query_chunks(uid_ints):
        placeholders = ",".join("?" for _uid in uid_chunk)
        cursor.execute(
            f"SELECT {columns} FROM [{table}] WHERE [UID] IN ({placeholders})",
            *uid_chunk,
        )
        rows.extend(cursor.fetchall())
    return rows


class MalformedBidOwnedUidError(RuntimeError):
    """A persisted bid-owned entity has no valid positive integer UID."""


class DuplicateBidOwnedUidError(RuntimeError):
    """A bid-owned table contains multiple rows for one authoritative UID."""


class MissingBidOwnedUidError(RuntimeError):
    """A required persisted owner or mutation target does not exist."""


class DanglingBidOwnedReferenceError(RuntimeError):
    """A persisted child points to an owner that does not exist."""


class CyclicBidOwnedReferenceError(RuntimeError):
    """A persisted self-referential ownership graph contains a cycle."""


class IncoherentBidOwnedScopeError(RuntimeError):
    """A mutation combines bid-owned entities from different authoritative bids."""


def require_takeoff_parent_pages(cursor, parent_page_pairs) -> None:
    pairs = [(int(parent), int(page)) for parent, page in parent_page_pairs]
    rows = _fetch_uid_rows(
        cursor,
        "BidTakeoffs",
        "[UID], [BidPageUID]",
        tuple(dict.fromkeys(parent for parent, _page in pairs)),
    )
    pages = {int(row[0]): int(row[1]) for row in rows}
    if any(pages.get(parent) != page for parent, page in pairs):
        raise IncoherentBidOwnedScopeError(
            BID_OWNED_IDENTITY_MESSAGE_A_TAKEOFF_AND_ITS_PARENT_MUST
        )


def require_plan_takeoff_ownership(
    cursor,
    schema: IDatabaseSchemaInspector,
    takeoff_uids: Sequence[int],
    ownership: Sequence[PlanTakeoffOwnership],
) -> None:
    if not ownership:
        return
    expected = {
        int(item.uid): tuple(
            int(value)
            for value in (
                item.page_uid,
                item.condition_uid,
                item.area_uid,
                item.parent_uid,
            )
        )
        for item in ownership
    }
    if set(expected) != set(takeoff_uids) or len(expected) != len(ownership):
        raise ValueError(
            BID_OWNED_IDENTITY_MESSAGE_THE_PLAN_OWNERSHIP_SNAPSHOT_MUST_COVER
        )
    columns = ["[UID]", "[BidPageUID]", "[BidConditionUID]"]
    for column in ("BidAreaUID", "ParentUID"):
        columns.append(
            f"[{column}]" if schema.column_exists("BidTakeoffs", column) else "NULL"
        )
    rows = _fetch_uid_rows(cursor, "BidTakeoffs", ", ".join(columns), tuple(expected))
    actual = {int(row[0]): tuple(int(value or 0) for value in row[1:]) for row in rows}
    if actual != expected or len(rows) != len(expected):
        raise MissingBidOwnedUidError(
            BID_OWNED_IDENTITY_MESSAGE_THE_TAKEOFF_OWNERSHIP_CHANGED_BEFORE_THE
        )


def require_valid_unique_bid_owned_uids(
    uid_values: Iterable[object],
    table: str,
) -> None:
    seen: set[str] = set()
    for raw_uid in uid_values:
        uid = "" if raw_uid is None else str(raw_uid)
        if not uid.isascii() or not uid.isdecimal() or int(uid) <= 0:
            rendered = uid if uid else "<missing>"
            raise MalformedBidOwnedUidError(
                BID_OWNED_IDENTITY_MESSAGE_CONTAINS_MALFORMED_UID_AUTHORITATIVE_BID_OWNED.format(
                    table=table, rendered=rendered
                )
            )
        canonical_uid = str(int(uid))
        if canonical_uid in seen:
            raise DuplicateBidOwnedUidError(
                BID_OWNED_IDENTITY_MESSAGE_CONTAINS_DUPLICATE_UID_AUTHORITATIVE_BID_OWNED.format(
                    table=table, canonical_uid=canonical_uid
                )
            )
        seen.add(canonical_uid)


def require_unique_bid_owned_uid_matches(cursor, table: str, uids) -> set[int]:
    uid_ints: list[int] = []
    seen: set[int] = set()
    for uid in uids:
        require_valid_unique_bid_owned_uids((uid,), table)
        uid_int = int(uid)
        if uid_int in seen:
            continue
        seen.add(uid_int)
        uid_ints.append(uid_int)
    if not uid_ints:
        return set()
    rows = _fetch_uid_rows(cursor, table, "[UID]", uid_ints)
    require_valid_unique_bid_owned_uids((row[0] for row in rows), table)
    return {int(row[0]) for row in rows}


def require_existing_unique_bid_owned_uid_matches(cursor, table: str, uids) -> None:
    requested = {int(uid) for uid in uids}
    matches = require_unique_bid_owned_uid_matches(cursor, table, requested)
    missing = sorted(requested - matches)
    if missing:
        raise MissingBidOwnedUidError(
            BID_OWNED_IDENTITY_MESSAGE_HAS_NO_ROW_FOR_UID_THE.format(
                table=table, missing=missing[0]
            )
        )


def require_existing_bid_scoped_uid_match(
    cursor,
    table: str,
    uid: object,
    bid_uid: object,
) -> None:
    require_existing_bid_scoped_uid_matches(cursor, table, (uid,), bid_uid)


def require_existing_bid_scoped_uid_matches(
    cursor,
    table: str,
    uids: Iterable[object],
    bid_uid: object,
) -> None:
    uid_ints: list[int] = []
    seen: set[int] = set()
    for uid in uids:
        require_valid_unique_bid_owned_uids((uid,), table)
        uid_int = int(uid)
        if uid_int in seen:
            continue
        seen.add(uid_int)
        uid_ints.append(uid_int)
    if not uid_ints:
        return
    rows = _fetch_uid_rows(cursor, table, "[UID], [BidUID]", uid_ints)
    require_valid_unique_bid_owned_uids((row[0] for row in rows), table)
    matches = {int(row[0]): row[1] for row in rows}
    missing = sorted(set(uid_ints) - set(matches))
    if missing:
        raise MissingBidOwnedUidError(
            BID_OWNED_IDENTITY_MESSAGE_HAS_NO_ROW_FOR_UID_THE.format(
                table=table, missing=missing[0]
            )
        )
    wrong_scope = next(
        (
            uid
            for uid in uid_ints
            if matches[uid] is None or int(matches[uid]) != int(bid_uid)
        ),
        None,
    )
    if wrong_scope is not None:
        raise MissingBidOwnedUidError(
            f"{table}.UID={wrong_scope} does not belong to " f"Bids.UID={int(bid_uid)}."
        )
    require_existing_unique_bid_owned_uid_matches(cursor, "Bids", (bid_uid,))


def require_single_bid_scope_for_uids(cursor, table: str, uids) -> int:
    uid_ints: list[int] = []
    seen: set[int] = set()
    for uid in uids:
        require_valid_unique_bid_owned_uids((uid,), table)
        uid_int = int(uid)
        if uid_int in seen:
            continue
        seen.add(uid_int)
        uid_ints.append(uid_int)
    if not uid_ints:
        raise MissingBidOwnedUidError(
            BID_OWNED_IDENTITY_MESSAGE_MUTATION_REQUIRES_AT_LEAST_ONE_AUTHORITATIVE.format(
                table=table
            )
        )
    rows = _fetch_uid_rows(cursor, table, "[UID], [BidUID]", uid_ints)
    require_valid_unique_bid_owned_uids((row[0] for row in rows), table)
    matches = {int(row[0]): row[1] for row in rows}
    missing = sorted(set(uid_ints) - set(matches))
    if missing:
        raise MissingBidOwnedUidError(
            BID_OWNED_IDENTITY_MESSAGE_HAS_NO_ROW_FOR_UID_THE.format(
                table=table, missing=missing[0]
            )
        )
    bid_uids = {int(bid_uid) for bid_uid in matches.values() if bid_uid is not None}
    if len(bid_uids) != 1 or any(bid_uid is None for bid_uid in matches.values()):
        raise IncoherentBidOwnedScopeError(
            BID_OWNED_IDENTITY_MESSAGE_MUTATION_TARGETS_DO_NOT_BELONG_TO.format(
                table=table
            )
        )
    bid_uid = next(iter(bid_uids))
    require_existing_unique_bid_owned_uid_matches(cursor, "Bids", (bid_uid,))
    return bid_uid


def require_existing_bid_owned_references(
    references: Iterable[tuple[object, object]],
    parent_uids: Iterable[object],
    *,
    child_table: str,
    child_column: str,
    parent_table: str,
) -> None:
    canonical_parents = {str(int(uid)) for uid in parent_uids}
    for raw_child_uid, raw_parent_uid in references:
        child_uid = str(int(raw_child_uid))
        parent_uid = str(int(raw_parent_uid))
        if parent_uid not in canonical_parents:
            raise DanglingBidOwnedReferenceError(
                f"{child_table}.UID={child_uid} references missing "
                f"{parent_table}.UID={parent_uid} through {child_column}."
            )


def require_acyclic_bid_owned_parent_graph(
    parent_uid_by_uid: dict[object, object],
    table: str,
    *,
    parent_column: str = "ParentUID",
) -> None:
    parent_map = {
        str(uid): str(parent_uid)
        for uid, parent_uid in parent_uid_by_uid.items()
        if parent_uid not in (None, "", 0, "0")
    }
    completed: set[str] = set()
    cycle_uids: set[str] = set()
    for start_uid in parent_map:
        if start_uid in completed:
            continue
        path: list[str] = []
        path_index: dict[str, int] = {}
        current_uid = start_uid
        while current_uid in parent_map and current_uid not in completed:
            if current_uid in path_index:
                cycle_uids.update(path[path_index[current_uid] :])
                break
            path_index[current_uid] = len(path)
            path.append(current_uid)
            current_uid = parent_map[current_uid]
        completed.update(path)
    if cycle_uids:
        uid = min(
            cycle_uids,
            key=lambda value: (
                0 if value.isascii() and value.isdecimal() else 1,
                int(value) if value.isascii() and value.isdecimal() else value,
            ),
        )
        raise CyclicBidOwnedReferenceError(
            f"{table}.UID={uid} participates in a {parent_column} cycle."
        )
