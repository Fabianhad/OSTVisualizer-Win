from __future__ import annotations
from typing import Callable, Iterable, Mapping, TypeAlias

MasterDataCandidateIndex: TypeAlias = dict[str, list[str]]


class AmbiguousMasterDataIdentityError(RuntimeError):
    """A weak import identity matched more than one master-data record."""


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
    result: MasterDataCandidateIndex = {}
    for raw_uid, raw_value in rows:
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
