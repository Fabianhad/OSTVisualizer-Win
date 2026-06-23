from typing import List, Optional


class ConditionFolderOperationsMixin:
    def insert_condition_folder(
        self,
        db_path: str,
        bid_uid: str,
        name: str,
        parent_uid: Optional[str] = None,
    ) -> Optional[str]:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                cursor = conn.cursor()
                new_uid = self._next_uid(cursor, "BidConditionFolders")
                parent_val = int(parent_uid) if parent_uid else None
                self._execute_insert_values(
                    cursor,
                    schema,
                    "BidConditionFolders",
                    {
                        "UID": new_uid,
                        "BidUID": int(bid_uid),
                        "ParentUID": parent_val,
                        "Name": name,
                        "ExpandState": -1,
                    },
                    ("UID", "BidUID", "Name"),
                    "insert_condition_folder",
                )
                return str(new_uid)
        except Exception:
            self.logger.exception("Failed to insert condition folder in %s", db_path)
            return None

    def rename_condition_folder(self, db_path: str, folder_uid: str, name: str) -> bool:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(
                    schema, "BidConditionFolders", ("UID", "Name")
                )
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE [BidConditionFolders] SET [Name] = ? WHERE [UID] = ?",
                    name,
                    int(folder_uid),
                )
                return True
        except Exception:
            self.logger.exception(
                "Failed to rename condition folder %s in %s", folder_uid, db_path
            )
            return False

    def delete_condition_folders(self, db_path: str, folder_uids: List[str]) -> bool:
        if not folder_uids:
            return True
        try:
            uids = [int(u) for u in folder_uids]
        except (TypeError, ValueError):
            self.logger.exception(
                "Invalid folder uids passed to delete_condition_folders: %s",
                folder_uids,
            )
            return False
        placeholders = ",".join("?" * len(uids))
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "BidConditionFolders", ("UID",))
                cursor = conn.cursor()
                if not schema.optional_table_missing(
                    "BidConditions"
                ) and schema.column_exists("BidConditions", "BidConditionFolderUID"):
                    cursor.execute(
                        "SELECT COUNT(*) FROM [BidConditions] "
                        f"WHERE [BidConditionFolderUID] IN ({placeholders})",
                        *uids,
                    )
                    row = cursor.fetchone()
                    if row and int(row[0] or 0) > 0:
                        self.logger.warning(
                            "Refusing to delete condition folders in use: %s", uids
                        )
                        return False
                cursor.execute(
                    f"DELETE FROM [BidConditionFolders] WHERE [UID] IN ({placeholders})",
                    *uids,
                )
                return True
        except Exception:
            self.logger.exception(
                "Failed to delete condition folders %s in %s", folder_uids, db_path
            )
            return False
