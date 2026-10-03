from typing import List, Optional
from ...database.bid_owned_identity import (
    BID_OWNED_IDENTITY_QUERY_CHUNK_SIZE,
    require_existing_unique_bid_owned_uid_matches,
    require_single_bid_scope_for_uids,
    require_unique_bid_owned_uid_matches,
)
from .constants import LAYER_REFERENCE_TABLES
from .identity_allocation import AccessIdentityAllocationMixin


def _default_layer_update_matched(
    cursor, assignment: str, value, layer_uid: int
) -> bool:
    if cursor.rowcount >= 0:
        return bool(cursor.rowcount)
    cursor.execute(
        "SELECT [UID] FROM [BidLayers] "
        f"WHERE [UID] = ? AND [IsTemplate] <> 0 AND {assignment}",
        layer_uid,
        value,
    )
    return cursor.fetchone() is not None


class LayerOperationsMixin(AccessIdentityAllocationMixin):
    def update_layer_show(self, db_path: str, layer_uid: str, show: bool) -> bool:
        show_value = -1 if show else 0
        with self._connection(db_path) as conn:
            schema = self._schema(conn)
            self._require_write_columns(schema, "BidLayers", ("UID", "Show"))
            cursor = conn.cursor()
            require_single_bid_scope_for_uids(cursor, "BidLayers", (layer_uid,))
            cursor.execute(
                "UPDATE [BidLayers] SET [Show] = ? WHERE [UID] = ?",
                show_value,
                int(layer_uid),
            )
            return True

    def update_default_layer_show(
        self, db_path: str, layer_uid: str, show: bool
    ) -> bool:
        show_value = -1 if show else 0
        with self._connection(db_path) as conn:
            schema = self._schema(conn)
            self._require_write_columns(
                schema, "BidLayers", ("UID", "Show", "IsTemplate")
            )
            cursor = conn.cursor()
            require_unique_bid_owned_uid_matches(cursor, "BidLayers", (layer_uid,))
            cursor.execute(
                "UPDATE [BidLayers] SET [Show] = ? "
                "WHERE [UID] = ? AND [IsTemplate] <> 0",
                show_value,
                int(layer_uid),
            )
            return _default_layer_update_matched(
                cursor, "[Show] = ?", show_value, int(layer_uid)
            )

    def insert_layer(
        self, db_path: str, bid_uid: str, name: str, after_sequence: int
    ) -> Optional[str]:
        with self._connection(db_path) as conn:
            schema = self._schema(conn)
            self._require_write_columns(schema, "BidLayers", ("UID", "BidUID", "Name"))
            cursor = conn.cursor()
            require_existing_unique_bid_owned_uid_matches(cursor, "Bids", (bid_uid,))
            has_sequence = schema.column_exists("BidLayers", "Sequence")
            if has_sequence:
                cursor.execute(
                    "UPDATE [BidLayers] SET [Sequence] = [Sequence] + 1 "
                    "WHERE [BidUID] = ? AND [Sequence] > ?",
                    int(bid_uid),
                    after_sequence,
                )
            else:
                schema.log_optional_write_skip("BidLayers", "Sequence", "insert_layer")
            new_uid = self._next_uid_preserving_references(cursor, schema, "BidLayers")
            new_seq = after_sequence + 1
            self._execute_insert_values(
                cursor,
                schema,
                "BidLayers",
                {
                    "UID": new_uid,
                    "BidUID": int(bid_uid),
                    "Name": name,
                    "Show": -1,
                    "Sequence": new_seq,
                    "IsTemplate": 0,
                    "IsLocked": 0,
                },
                ("UID", "BidUID", "Name"),
                "insert_layer",
            )
            return str(new_uid)

    def insert_default_layer(
        self, db_path: str, name: str, after_sequence: int
    ) -> Optional[str]:
        with self._connection(db_path) as conn:
            schema = self._schema(conn)
            self._require_write_columns(
                schema, "BidLayers", ("UID", "Name", "IsTemplate")
            )
            cursor = conn.cursor()
            if schema.column_exists("BidLayers", "Sequence"):
                cursor.execute(
                    "UPDATE [BidLayers] SET [Sequence] = [Sequence] + 1 "
                    "WHERE [Sequence] > ? AND [IsTemplate] <> 0",
                    after_sequence,
                )
            else:
                schema.log_optional_write_skip(
                    "BidLayers", "Sequence", "insert_default_layer"
                )
            new_uid = self._next_uid_preserving_references(cursor, schema, "BidLayers")
            self._execute_insert_values(
                cursor,
                schema,
                "BidLayers",
                {
                    "UID": new_uid,
                    "Name": name,
                    "Show": -1,
                    "Sequence": after_sequence + 1,
                    "IsTemplate": -1,
                    "IsLocked": -1,
                },
                ("UID", "Name", "IsTemplate"),
                "insert_default_layer",
            )
            return str(new_uid)

    def delete_layer(self, db_path: str, layer_uid: str) -> bool:
        with self._connection(db_path) as conn:
            schema = self._schema(conn)
            self._require_write_columns(schema, "BidLayers", ("UID",))
            cursor = conn.cursor()
            require_single_bid_scope_for_uids(cursor, "BidLayers", (layer_uid,))
            select_cols = ["[UID]"]
            if schema.column_exists("BidLayers", "Sequence"):
                select_cols.append("[Sequence]")
            else:
                select_cols.append("NULL AS [Sequence]")
            if schema.column_exists("BidLayers", "BidUID"):
                select_cols.append("[BidUID]")
            else:
                select_cols.append("NULL AS [BidUID]")
            where_parts = ["[UID] = ?"]
            if schema.column_exists("BidLayers", "IsTemplate"):
                where_parts.append("[IsTemplate] = 0")
            if schema.column_exists("BidLayers", "IsLocked"):
                where_parts.append("[IsLocked] = 0")
            cursor.execute(
                f"SELECT {', '.join(select_cols)} FROM [BidLayers] "
                f"WHERE {' AND '.join(where_parts)}",
                int(layer_uid),
            )
            row = cursor.fetchone()
            if not row:
                return False
            deleted_seq = row.Sequence
            bid_uid = row.BidUID
            layer_int = int(layer_uid)
            for table in LAYER_REFERENCE_TABLES:
                if schema.optional_table_missing(table) or not schema.column_exists(
                    table, "BidLayerUID"
                ):
                    continue
                try:
                    cursor.execute(
                        f"UPDATE [{table}] SET [BidLayerUID]=NULL "
                        "WHERE [BidLayerUID]=?",
                        layer_int,
                    )
                except Exception as exc:
                    if self._record_caught_mutation_error(exc):
                        raise
                    self.logger.warning(
                        "Failed to clear BidLayerUID in %s for layer %s: %s",
                        table,
                        layer_int,
                        exc,
                    )
            cursor.execute("DELETE FROM [BidLayers] WHERE [UID] = ?", layer_int)
            if (
                deleted_seq is not None
                and bid_uid is not None
                and schema.column_exists("BidLayers", "Sequence")
                and schema.column_exists("BidLayers", "BidUID")
            ):
                cursor.execute(
                    "UPDATE [BidLayers] SET [Sequence] = [Sequence] - 1 "
                    "WHERE [BidUID] = ? AND [Sequence] > ?",
                    bid_uid,
                    deleted_seq,
                )
            return True

    def delete_default_layer(self, db_path: str, layer_uid: str) -> bool:
        with self._connection(db_path) as conn:
            schema = self._schema(conn)
            self._require_write_columns(schema, "BidLayers", ("UID", "IsTemplate"))
            cursor = conn.cursor()
            require_unique_bid_owned_uid_matches(cursor, "BidLayers", (layer_uid,))
            select_cols = ["[UID]"]
            if schema.column_exists("BidLayers", "Sequence"):
                select_cols.append("[Sequence]")
            else:
                select_cols.append("NULL AS [Sequence]")
            cursor.execute(
                f"SELECT {', '.join(select_cols)} FROM [BidLayers] "
                "WHERE [UID] = ? AND [IsTemplate] <> 0",
                int(layer_uid),
            )
            row = cursor.fetchone()
            if not row:
                return False
            deleted_seq = row.Sequence
            cursor.execute(
                "DELETE FROM [BidLayers] WHERE [UID] = ? AND [IsTemplate] <> 0",
                int(layer_uid),
            )
            if deleted_seq is not None and schema.column_exists(
                "BidLayers", "Sequence"
            ):
                cursor.execute(
                    "UPDATE [BidLayers] SET [Sequence] = [Sequence] - 1 "
                    "WHERE [Sequence] > ? AND [IsTemplate] <> 0",
                    deleted_seq,
                )
            return True

    def update_all_layers_show(
        self,
        db_path: str,
        bid_uid: str,
        show: bool,
        layer_uids: Optional[List[str]] = None,
    ) -> bool:
        show_value = -1 if show else 0
        with self._connection(db_path) as conn:
            schema = self._schema(conn)
            self._require_write_columns(schema, "BidLayers", ("BidUID", "Show"))
            template_filter = ""
            if schema.column_exists("BidLayers", "IsTemplate") and schema.column_exists(
                "BidLayers", "IsLocked"
            ):
                template_filter = " OR ([IsTemplate] <> 0 AND [IsLocked] <> 0)"
            cursor = conn.cursor()
            require_existing_unique_bid_owned_uid_matches(cursor, "Bids", (bid_uid,))
            if layer_uids is not None:
                normalized_uids = []
                seen_uids = set()
                for layer_uid in layer_uids:
                    layer_uid_int = int(layer_uid)
                    if layer_uid_int in seen_uids:
                        continue
                    seen_uids.add(layer_uid_int)
                    normalized_uids.append(layer_uid_int)
                if not normalized_uids:
                    return True
                chunks = [
                    normalized_uids[start : start + BID_OWNED_IDENTITY_QUERY_CHUNK_SIZE]
                    for start in range(
                        0,
                        len(normalized_uids),
                        BID_OWNED_IDENTITY_QUERY_CHUNK_SIZE,
                    )
                ]
                for chunk in chunks:
                    placeholders = ", ".join("?" for _uid in chunk)
                    cursor.execute(
                        "SELECT [UID] FROM [BidLayers] "
                        f"WHERE [UID] IN ({placeholders}) AND "
                        f"([BidUID] = ?{template_filter})",
                        *chunk,
                        int(bid_uid),
                    )
                    eligible_uid_rows = [int(row[0]) for row in cursor.fetchall()]
                    if len(eligible_uid_rows) != len(chunk) or set(
                        eligible_uid_rows
                    ) != set(chunk):
                        return False
                for chunk in chunks:
                    placeholders = ", ".join("?" for _uid in chunk)
                    cursor.execute(
                        "UPDATE [BidLayers] SET [Show] = ? "
                        f"WHERE [UID] IN ({placeholders}) AND "
                        f"([BidUID] = ?{template_filter})",
                        show_value,
                        *chunk,
                        int(bid_uid),
                    )
                    affected_rows = int(cursor.rowcount)
                    if affected_rows >= 0 and affected_rows != len(chunk):
                        raise RuntimeError(
                            "The bulk Layer visibility update affected "
                            f"{affected_rows} of {len(chunk)} captured Layers in "
                            f"a {len(normalized_uids)}-Layer operation."
                        )
                    if affected_rows < 0:
                        cursor.execute(
                            "SELECT [UID] FROM [BidLayers] "
                            f"WHERE [UID] IN ({placeholders}) AND [Show] = ? AND "
                            f"([BidUID] = ?{template_filter})",
                            *chunk,
                            show_value,
                            int(bid_uid),
                        )
                        verified_uid_rows = [int(row[0]) for row in cursor.fetchall()]
                        if len(verified_uid_rows) != len(chunk) or set(
                            verified_uid_rows
                        ) != set(chunk):
                            raise RuntimeError(
                                "The bulk Layer visibility update could verify only "
                                f"{len(verified_uid_rows)} of {len(chunk)} captured Layers "
                                f"in a {len(normalized_uids)}-Layer operation."
                            )
                return True
            cursor.execute(
                "UPDATE [BidLayers] SET [Show] = ? "
                f"WHERE [BidUID] = ?{template_filter}",
                show_value,
                int(bid_uid),
            )
            return True

    def update_all_default_layers_show(self, db_path: str, show: bool) -> bool:
        show_value = -1 if show else 0
        with self._connection(db_path) as conn:
            schema = self._schema(conn)
            self._require_write_columns(schema, "BidLayers", ("Show", "IsTemplate"))
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE [BidLayers] SET [Show] = ? WHERE [IsTemplate] <> 0",
                show_value,
            )
            return True

    def update_layer_name(self, db_path: str, layer_uid: str, name: str) -> bool:
        with self._connection(db_path) as conn:
            schema = self._schema(conn)
            self._require_write_columns(schema, "BidLayers", ("UID", "Name"))
            where_parts = ["[UID] = ?"]
            if schema.column_exists("BidLayers", "IsTemplate"):
                where_parts.append("[IsTemplate] = 0")
            if schema.column_exists("BidLayers", "IsLocked"):
                where_parts.append("[IsLocked] = 0")
            cursor = conn.cursor()
            require_single_bid_scope_for_uids(cursor, "BidLayers", (layer_uid,))
            cursor.execute(
                "UPDATE [BidLayers] SET [Name] = ? "
                f"WHERE {' AND '.join(where_parts)}",
                name,
                int(layer_uid),
            )
            return True

    def update_default_layer_name(
        self, db_path: str, layer_uid: str, name: str
    ) -> bool:
        with self._connection(db_path) as conn:
            schema = self._schema(conn)
            self._require_write_columns(
                schema, "BidLayers", ("UID", "Name", "IsTemplate")
            )
            cursor = conn.cursor()
            require_unique_bid_owned_uid_matches(cursor, "BidLayers", (layer_uid,))
            cursor.execute(
                "UPDATE [BidLayers] SET [Name] = ? "
                "WHERE [UID] = ? AND [IsTemplate] <> 0",
                name,
                int(layer_uid),
            )
            return _default_layer_update_matched(
                cursor, "[Name] = ?", name, int(layer_uid)
            )

    def swap_layer_sequence(
        self, db_path: str, layer_uid_a: str, layer_uid_b: str
    ) -> bool:
        with self._connection(db_path) as conn:
            schema = self._schema(conn)
            self._require_write_columns(schema, "BidLayers", ("UID", "Sequence"))
            cursor = conn.cursor()
            require_single_bid_scope_for_uids(
                cursor, "BidLayers", (layer_uid_a, layer_uid_b)
            )
            cursor.execute(
                "SELECT [UID], [Sequence] FROM [BidLayers] WHERE [UID] IN (?, ?)",
                int(layer_uid_a),
                int(layer_uid_b),
            )
            rows = cursor.fetchall()
            if len(rows) != 2:
                return False
            seq_map = {str(r.UID): r.Sequence for r in rows}
            seq_a = seq_map.get(layer_uid_a)
            seq_b = seq_map.get(layer_uid_b)
            if seq_a is None or seq_b is None:
                return False
            cursor.execute(
                "UPDATE [BidLayers] SET [Sequence] = ? WHERE [UID] = ?",
                seq_b,
                int(layer_uid_a),
            )
            cursor.execute(
                "UPDATE [BidLayers] SET [Sequence] = ? WHERE [UID] = ?",
                seq_a,
                int(layer_uid_b),
            )
            return True

    def swap_default_layer_sequence(
        self, db_path: str, layer_uid_a: str, layer_uid_b: str
    ) -> bool:
        with self._connection(db_path) as conn:
            schema = self._schema(conn)
            self._require_write_columns(
                schema, "BidLayers", ("UID", "Sequence", "IsTemplate")
            )
            cursor = conn.cursor()
            require_unique_bid_owned_uid_matches(
                cursor, "BidLayers", (layer_uid_a, layer_uid_b)
            )
            cursor.execute(
                "SELECT [UID], [Sequence] FROM [BidLayers] "
                "WHERE [UID] IN (?, ?) AND [IsTemplate] <> 0",
                int(layer_uid_a),
                int(layer_uid_b),
            )
            rows = cursor.fetchall()
            if len(rows) != 2:
                return False
            seq_map = {str(r.UID): r.Sequence for r in rows}
            seq_a = seq_map.get(layer_uid_a)
            seq_b = seq_map.get(layer_uid_b)
            if seq_a is None or seq_b is None:
                return False
            cursor.execute(
                "UPDATE [BidLayers] SET [Sequence] = ? WHERE [UID] = ?",
                seq_b,
                int(layer_uid_a),
            )
            cursor.execute(
                "UPDATE [BidLayers] SET [Sequence] = ? WHERE [UID] = ?",
                seq_a,
                int(layer_uid_b),
            )
            return True
