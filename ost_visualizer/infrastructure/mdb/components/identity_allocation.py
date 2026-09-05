from ..raw_bid_integrity import BID_RELATIONSHIPS


class AccessIdentityAllocationMixin:
    def _next_uid(self, cursor, table: str) -> int:
        cursor.execute(f"SELECT MAX([UID]) FROM [{table}]")
        result = cursor.fetchone()[0]
        return int(result) + 1 if result is not None else 1

    def _next_uid_preserving_references(self, cursor, schema, table: str) -> int:
        next_uid = self._next_uid(cursor, table)
        checked: set[tuple[str, str]] = set()
        for relationship in BID_RELATIONSHIPS:
            if (
                relationship.parent_table != table
                or relationship.parent_column != "UID"
            ):
                continue
            reference = (relationship.child_table, relationship.child_column)
            if reference in checked:
                continue
            checked.add(reference)
            if schema.optional_table_missing(
                relationship.child_table
            ) or not schema.column_exists(
                relationship.child_table, relationship.child_column
            ):
                continue
            cursor.execute(
                f"SELECT MAX([{relationship.child_column}]) "
                f"FROM [{relationship.child_table}]"
            )
            row = cursor.fetchone()
            if row is None or row[0] in (None, "", 0, "0"):
                continue
            referenced_uid = int(row[0])
            if referenced_uid >= next_uid:
                next_uid = referenced_uid + 1
        return next_uid
