from typing import List, Optional
from ...database.bid_owned_identity import (
    require_existing_bid_scoped_uid_match,
    require_existing_unique_bid_owned_uid_matches,
    require_single_bid_scope_for_uids,
)
from .identity_allocation import AccessIdentityAllocationMixin


class ConditionFolderOperationsMixin(AccessIdentityAllocationMixin):
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
                require_existing_unique_bid_owned_uid_matches(
                    cursor, "Bids", (bid_uid,)
                )
                if parent_uid:
                    if not schema.column_exists("BidConditionFolders", "ParentUID"):
                        raise RuntimeError(
                            "This OST database does not support Condition folder "
                            "hierarchy persistence."
                        )
                    require_existing_bid_scoped_uid_match(
                        cursor,
                        "BidConditionFolders",
                        parent_uid,
                        bid_uid,
                    )
                new_uid = self._next_uid_preserving_references(
                    cursor, schema, "BidConditionFolders"
                )
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
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
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
                require_single_bid_scope_for_uids(
                    cursor, "BidConditionFolders", (folder_uid,)
                )
                cursor.execute(
                    "UPDATE [BidConditionFolders] SET [Name] = ? WHERE [UID] = ?",
                    name,
                    int(folder_uid),
                )
                return True
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception(
                "Failed to rename condition folder %s in %s", folder_uid, db_path
            )
            return False

    def delete_condition_folders(self, db_path: str, folder_uids: List[str]) -> bool:
        if not folder_uids:
            return True
        try:
            uids = [int(u) for u in folder_uids]
        except (TypeError, ValueError) as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.warning(
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
                require_single_bid_scope_for_uids(cursor, "BidConditionFolders", uids)
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
                if schema.column_exists("BidConditionFolders", "ParentUID"):
                    cursor.execute(
                        "UPDATE [BidConditionFolders] SET [ParentUID]=NULL "
                        f"WHERE [ParentUID] IN ({placeholders})",
                        *uids,
                    )
                cursor.execute(
                    f"DELETE FROM [BidConditionFolders] WHERE [UID] IN ({placeholders})",
                    *uids,
                )
                return True
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception(
                "Failed to delete condition folders %s in %s", folder_uids, db_path
            )
            return False
