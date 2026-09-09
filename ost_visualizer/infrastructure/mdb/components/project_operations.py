from typing import List, Optional
from ...database.bid_owned_identity import (
    require_existing_unique_bid_owned_uid_matches,
    require_unique_bid_owned_uid_matches,
)
from .identity_allocation import AccessIdentityAllocationMixin


class ProjectOperationsMixin(AccessIdentityAllocationMixin):
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
            uids = self._normalize_int_uids(bid_uids, "Bids")
        except (TypeError, ValueError) as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.warning(
                "Invalid bid uids passed to move_bids_to_project: %s", bid_uids
            )
            return False
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "Bids", ("UID", "BidProjectUID"))
                cursor = conn.cursor()
                require_existing_unique_bid_owned_uid_matches(cursor, "Bids", uids)
                require_existing_unique_bid_owned_uid_matches(
                    cursor, "BidProjects", (project_uid,)
                )
                if orig_project_uid is not None:
                    require_existing_unique_bid_owned_uid_matches(
                        cursor, "BidProjects", (orig_project_uid,)
                    )
                if orig_project_uid is not None and schema.column_exists(
                    "Bids", "OrigBidProjectUID"
                ):
                    self._execute_uid_in_update_chunks(
                        cursor,
                        "Bids",
                        "UID",
                        {
                            "BidProjectUID": project_uid,
                            "OrigBidProjectUID": orig_project_uid,
                        },
                        uids,
                    )
                else:
                    if orig_project_uid is not None:
                        schema.log_optional_write_skip(
                            "Bids", "OrigBidProjectUID", "move_bids_to_project"
                        )
                    self._execute_uid_in_update_chunks(
                        cursor,
                        "Bids",
                        "UID",
                        {"BidProjectUID": project_uid},
                        uids,
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
            uids = self._normalize_int_uids(bid_uids, "Bids")
        except (TypeError, ValueError) as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.warning("Invalid bid uids passed to orphan_bids: %s", bid_uids)
            return False
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "Bids", ("UID", "BidProjectUID"))
                cursor = conn.cursor()
                require_unique_bid_owned_uid_matches(cursor, "Bids", uids)
                self._execute_uid_in_update_chunks(
                    cursor,
                    "Bids",
                    "UID",
                    {"BidProjectUID": None},
                    uids,
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
                new_uid = str(
                    self._next_uid_preserving_references(cursor, schema, "BidProjects")
                )
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
                require_unique_bid_owned_uid_matches(
                    cursor, "BidProjects", (project_uid,)
                )
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
            uids = self._normalize_int_uids(project_uids, "BidProjects")
        except (TypeError, ValueError) as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.warning(
                "Invalid project uids passed to delete_projects: %s", project_uids
            )
            return False
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "BidProjects", ("UID",))
                cursor = conn.cursor()
                require_unique_bid_owned_uid_matches(cursor, "BidProjects", uids)
                if not schema.optional_table_missing("Bids") and schema.column_exists(
                    "Bids", "BidProjectUID"
                ):
                    self._execute_uid_in_update_chunks(
                        cursor,
                        "Bids",
                        "BidProjectUID",
                        {"BidProjectUID": None},
                        uids,
                    )
                if not schema.optional_table_missing("Bids") and schema.column_exists(
                    "Bids", "OrigBidProjectUID"
                ):
                    self._execute_uid_in_update_chunks(
                        cursor,
                        "Bids",
                        "OrigBidProjectUID",
                        {"OrigBidProjectUID": None},
                        uids,
                    )
                self._execute_uid_in_delete_chunks(cursor, "BidProjects", "UID", uids)
                return True
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception(
                "Failed to delete projects %s from %s", project_uids, db_path
            )
            return False
