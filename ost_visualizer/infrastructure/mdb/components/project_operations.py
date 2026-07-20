from typing import List, Optional
from .sql_helpers import placeholders


class ProjectOperationsMixin:
    def move_bids_to_project(
        self,
        db_path: str,
        bid_uids: List[str],
        project_uid: str,
        orig_project_uid: Optional[str] = None,
    ) -> bool:
        if not bid_uids:
            return True
        try:
            uids = [int(u) for u in bid_uids]
        except (TypeError, ValueError) as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.warning(
                "Invalid bid uids passed to move_bids_to_project: %s", bid_uids
            )
            return False
        placeholders_sql = placeholders(uids)
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "Bids", ("UID", "BidProjectUID"))
                cursor = conn.cursor()
                if orig_project_uid is not None and schema.column_exists(
                    "Bids", "OrigBidProjectUID"
                ):
                    cursor.execute(
                        "UPDATE [Bids] SET BidProjectUID = ?, OrigBidProjectUID = ? "
                        f"WHERE UID IN ({placeholders_sql})",
                        project_uid,
                        orig_project_uid,
                        *uids,
                    )
                else:
                    if orig_project_uid is not None:
                        schema.log_optional_write_skip(
                            "Bids", "OrigBidProjectUID", "move_bids_to_project"
                        )
                    cursor.execute(
                        "UPDATE [Bids] SET BidProjectUID = ? "
                        f"WHERE UID IN ({placeholders_sql})",
                        project_uid,
                        *uids,
                    )
                return True
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception(
                "Failed to move bids %s to project %s in %s",
                bid_uids,
                project_uid,
                db_path,
            )
            return False

    def orphan_bids(self, db_path: str, bid_uids: List[str]) -> bool:
        if not bid_uids:
            return True
        try:
            uids = [int(u) for u in bid_uids]
        except (TypeError, ValueError) as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.warning("Invalid bid uids passed to orphan_bids: %s", bid_uids)
            return False
        placeholders_sql = placeholders(uids)
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "Bids", ("UID", "BidProjectUID"))
                cursor = conn.cursor()
                cursor.execute(
                    f"UPDATE [Bids] SET BidProjectUID = NULL WHERE UID IN ({placeholders_sql})",
                    *uids,
                )
                return True
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception("Failed to orphan bids %s in %s", bid_uids, db_path)
            return False

    def create_project(self, db_path: str, name: str) -> Optional[str]:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "BidProjects", ("UID", "Name"))
                cursor = conn.cursor()
                new_uid = str(self._next_uid(cursor, "BidProjects"))
                cursor.execute(
                    "INSERT INTO [BidProjects] ([UID], [Name]) VALUES (?, ?)",
                    new_uid,
                    name,
                )
                return new_uid
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception("Failed to create project in %s", db_path)
            return None

    def rename_project(self, db_path: str, project_uid: str, new_name: str) -> bool:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "BidProjects", ("UID", "Name"))
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE [BidProjects] SET [Name] = ? WHERE UID = ?",
                    new_name,
                    project_uid,
                )
                return True
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception(
                "Failed to rename project %s in %s", project_uid, db_path
            )
            return False

    def delete_projects(self, db_path: str, project_uids: List[str]) -> bool:
        if not project_uids:
            return True
        try:
            uids = [int(u) for u in project_uids]
        except (TypeError, ValueError) as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.warning(
                "Invalid project uids passed to delete_projects: %s", project_uids
            )
            return False
        placeholders_sql = placeholders(uids)
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "BidProjects", ("UID",))
                cursor = conn.cursor()
                if not schema.optional_table_missing("Bids") and schema.column_exists(
                    "Bids", "BidProjectUID"
                ):
                    cursor.execute(
                        "UPDATE [Bids] SET [BidProjectUID]=NULL "
                        f"WHERE [BidProjectUID] IN ({placeholders_sql})",
                        *uids,
                    )
                cursor.execute(
                    f"DELETE FROM [BidProjects] WHERE UID IN ({placeholders_sql})",
                    *uids,
                )
                return True
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception(
                "Failed to delete projects %s from %s", project_uids, db_path
            )
            return False
