from __future__ import annotations
from typing import Callable, Iterable, Mapping, TypeAlias

MasterDataCandidateIndex: TypeAlias = dict[str, list[str]]


class AmbiguousMasterDataIdentityError(RuntimeError):
    """A weak import identity matched more than one master-data record."""


class DuplicateMasterDataUidError(RuntimeError):
    """A master-data table contains more than one row for an authoritative UID."""


class MissingMasterDataIdentityError(RuntimeError):
    """A referenced authoritative master-data record does not exist."""


def require_unique_master_data_uids(uid_values: Iterable[object], table: str) -> None:
    seen: set[str] = set()
    for raw_uid in uid_values:
        uid = "" if raw_uid is None else str(raw_uid)
        if uid in seen:
            raise DuplicateMasterDataUidError(
                f"{table} contains duplicate UID {uid}; "
                "authoritative master-data UIDs must be unique."
            )
        seen.add(uid)


def require_existing_unique_master_data_uid(cursor, table: str, uid: int) -> None:
    cursor.execute(f"SELECT [UID] FROM [{table}] WHERE [UID]=?", uid)
    rows = cursor.fetchall()
    require_unique_master_data_uids((row[0] for row in rows), table)
    if not rows:
        raise MissingMasterDataIdentityError(
            f"{table} has no row for UID {uid}; "
            "the referenced authoritative master-data record does not exist."
        )


def require_optional_existing_unique_master_data_uid(
    cursor,
    table: str,
    value: object,
) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("Boolean values are not valid master-data identifiers")
    if isinstance(value, int):
        uid = value
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        uid = int(stripped)
    else:
        raise TypeError(f"Unsupported master-data identifier: {type(value).__name__}")
    require_existing_unique_master_data_uid(cursor, table, uid)
    return uid


def master_data_identity_key(table: str, column: str, value: object) -> str:
    text = "" if value is None else str(value)
    if table == "CdnTypes" and column == "Name":
        return text.strip().lower()
    return text


def build_master_data_candidate_index(
    rows: Iterable[tuple[object, object]],
    table: str,
    column: str,
) -> MasterDataCandidateIndex:
    source_rows = list(rows)
    require_unique_master_data_uids((row[0] for row in source_rows), table)
    result: MasterDataCandidateIndex = {}
    for raw_uid, raw_value in source_rows:
        add_master_data_candidate(
            result,
            master_data_identity_key(table, column, raw_value),
            "" if raw_uid is None else str(raw_uid),
        )
    return result


def add_master_data_candidate(
    candidates: MasterDataCandidateIndex,
    key: str,
    uid: str,
) -> None:
    matching = candidates.setdefault(key, [])
    if uid not in matching:
        matching.append(uid)


def resolve_master_data_candidate(
    candidates: MasterDataCandidateIndex,
    key: str,
    identity_label: str,
) -> str | None:
    matching = candidates.get(key, [])
    if len(matching) > 1:
        joined = ", ".join(sorted(matching))
        raise AmbiguousMasterDataIdentityError(
            f"Imported master-data identity is ambiguous for {identity_label}: "
            f"matching UIDs {joined}."
        )
    return matching[0] if matching else None


def require_unambiguous_incoming_identities(
    rows: Iterable[Mapping[str, object]],
    identity_key: Callable[[Mapping[str, object]], str],
    identity_label: str,
    *,
    ignore_empty: bool = False,
) -> None:
    candidates: MasterDataCandidateIndex = {}
    for position, row in enumerate(rows, start=1):
        key = identity_key(row)
        if ignore_empty and not key:
            continue
        raw_uid = row.get("UID")
        source_identity = (
            str(raw_uid) if raw_uid not in (None, "") else f"source row {position}"
        )
        add_master_data_candidate(candidates, key, source_identity)
    for key in candidates:
        resolve_master_data_candidate(candidates, key, identity_label)
