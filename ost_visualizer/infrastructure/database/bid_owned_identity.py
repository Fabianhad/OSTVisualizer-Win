from __future__ import annotations
from collections.abc import Iterable


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
                f"{table} contains malformed UID {rendered}; "
                "authoritative bid-owned UIDs must be positive integers."
            )
        canonical_uid = str(int(uid))
        if canonical_uid in seen:
            raise DuplicateBidOwnedUidError(
                f"{table} contains duplicate UID {canonical_uid}; "
                "authoritative bid-owned UIDs must be unique."
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
    placeholders = ",".join("?" for _uid in uid_ints)
    cursor.execute(
        f"SELECT [UID] FROM [{table}] WHERE [UID] IN ({placeholders})",
        *uid_ints,
    )
    rows = cursor.fetchall()
    require_valid_unique_bid_owned_uids((row[0] for row in rows), table)
    return {int(row[0]) for row in rows}


def require_existing_unique_bid_owned_uid_matches(cursor, table: str, uids) -> None:
    requested = {int(uid) for uid in uids}
    matches = require_unique_bid_owned_uid_matches(cursor, table, requested)
    missing = sorted(requested - matches)
    if missing:
        raise MissingBidOwnedUidError(
            f"{table} has no row for UID {missing[0]}; "
            "the requested authoritative owner does not exist."
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
    placeholders = ",".join("?" for _uid in uid_ints)
    cursor.execute(
        f"SELECT [UID], [BidUID] FROM [{table}] " f"WHERE [UID] IN ({placeholders})",
        *uid_ints,
    )
    rows = cursor.fetchall()
    require_valid_unique_bid_owned_uids((row[0] for row in rows), table)
    matches = {int(row[0]): row[1] for row in rows}
    missing = sorted(set(uid_ints) - set(matches))
    if missing:
        raise MissingBidOwnedUidError(
            f"{table} has no row for UID {missing[0]}; "
            "the requested authoritative owner does not exist."
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
            f"{table} mutation requires at least one authoritative target."
        )
    placeholders = ",".join("?" for _uid in uid_ints)
    cursor.execute(
        f"SELECT [UID], [BidUID] FROM [{table}] " f"WHERE [UID] IN ({placeholders})",
        *uid_ints,
    )
    rows = cursor.fetchall()
    require_valid_unique_bid_owned_uids((row[0] for row in rows), table)
    matches = {int(row[0]): row[1] for row in rows}
    missing = sorted(set(uid_ints) - set(matches))
    if missing:
        raise MissingBidOwnedUidError(
            f"{table} has no row for UID {missing[0]}; "
            "the requested authoritative owner does not exist."
        )
    bid_uids = {int(bid_uid) for bid_uid in matches.values() if bid_uid is not None}
    if len(bid_uids) != 1 or any(bid_uid is None for bid_uid in matches.values()):
        raise IncoherentBidOwnedScopeError(
            f"{table} mutation targets do not belong to one authoritative Bid."
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
