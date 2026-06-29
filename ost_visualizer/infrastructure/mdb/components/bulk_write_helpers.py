from collections.abc import Iterable, Iterator, Sequence
import pyodbc
from .sql_helpers import placeholders

ACCESS_BULK_CHUNK_SIZE = 50


class AccessBulkWriteMixin:
    def _normalize_int_uids(self, uids: Iterable, label: str) -> list[int]:
        if uids is None or isinstance(uids, (str, bytes)):
            raise ValueError(f"Invalid {label} UID collection: {uids!r}")
        normalized: list[int] = []
        seen: set[int] = set()
        for uid in uids:
            try:
                uid_int = int(uid)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid {label} UID: {uid!r}") from exc
            if uid_int in seen:
                continue
            seen.add(uid_int)
            normalized.append(uid_int)
        return normalized

    def _iter_access_chunks(
        self,
        values: Sequence[int],
        chunk_size: int = ACCESS_BULK_CHUNK_SIZE,
    ) -> Iterator[list[int]]:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        for start in range(0, len(values), chunk_size):
            yield list(values[start : start + chunk_size])

    def _execute_uid_in_update_chunks(
        self,
        cursor,
        table: str,
        uid_column: str,
        set_values: dict,
        uid_ints: Sequence[int],
        chunk_size: int = ACCESS_BULK_CHUNK_SIZE,
    ) -> None:
        if not uid_ints:
            return
        if not set_values:
            raise ValueError("No values supplied for chunked UID update.")
        set_clause = ", ".join(f"[{column}]=?" for column in set_values)
        set_params = list(set_values.values())
        for chunk in self._iter_access_chunks(uid_ints, chunk_size):
            where_sql, where_params = self._uid_where_clause(uid_column, chunk)
            cursor.execute(
                f"UPDATE [{table}] SET {set_clause} WHERE {where_sql}",
                *(set_params + where_params),
            )

    def _execute_uid_in_delete_chunks(
        self,
        cursor,
        table: str,
        uid_column: str,
        uid_ints: Sequence[int],
        chunk_size: int = ACCESS_BULK_CHUNK_SIZE,
    ) -> None:
        if not uid_ints:
            return
        for chunk in self._iter_access_chunks(uid_ints, chunk_size):
            where_sql, where_params = self._uid_where_clause(uid_column, chunk)
            cursor.execute(
                f"DELETE FROM [{table}] WHERE {where_sql}",
                *where_params,
            )

    def _is_access_resource_exceeded(self, exc: BaseException) -> bool:
        if not isinstance(exc, pyodbc.Error):
            return False
        messages = [str(arg) for arg in exc.args]
        messages.append(str(exc))
        return any(
            "HY001" in message or "System resource exceeded" in message
            for message in messages
        )

    @staticmethod
    def _uid_where_clause(uid_column: str, uid_ints: Sequence[int]) -> tuple[str, list]:
        if len(uid_ints) == 1:
            return f"[{uid_column}]=?", [uid_ints[0]]
        return f"[{uid_column}] IN ({placeholders(uid_ints)})", list(uid_ints)
