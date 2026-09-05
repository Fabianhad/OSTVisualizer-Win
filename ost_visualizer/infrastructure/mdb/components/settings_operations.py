import uuid
from typing import Any, Dict, Optional
import pyodbc
from ..bid_settings_contract import fetch_optional_bid_settings_row
from ....domain.entities.area import BidAreaChangeset
from ....domain.services.uom_service import normalize_uom_for_system
from ...database.master_data_identity import (
    require_existing_unique_master_data_uid,
    require_unique_master_data_uids,
)
from ...database.bid_owned_identity import (
    DanglingBidOwnedReferenceError,
    MissingBidOwnedUidError,
    require_acyclic_bid_owned_parent_graph,
    require_existing_bid_scoped_uid_matches,
    require_existing_unique_bid_owned_uid_matches,
    require_single_bid_scope_for_uids,
    require_unique_bid_owned_uid_matches,
    require_valid_unique_bid_owned_uids,
)
from ...parsers.position_parser import convert_elevation_in_name
from .constants import (
    COVER_SHEET_PAGE_SELECTION_TYPE,
    PAGE_DELETE_CHILD_TABLES,
    TAKEOFF_ANNOTATION_REFERENCE_COLUMNS,
    TAKEOFF_REFERENCE_TABLES,
    TAKEOFF_SELF_REFERENCE_COLUMNS,
)
from .identity_allocation import AccessIdentityAllocationMixin
from .overlay_rect import (
    overlay_path_storage_identity,
    replacement_overlay_storage_values,
)
from .serialization import encode_text_blob


def _require_unique_master_data_row(cursor, table: str, uid: int) -> None:
    cursor.execute(f"SELECT [UID] FROM [{table}] WHERE [UID]=?", uid)
    require_unique_master_data_uids(
        (row[0] for row in cursor.fetchall()),
        table,
    )


class SettingsOperationsMixin(AccessIdentityAllocationMixin):
    @staticmethod
    def _windows_path_separators(path) -> str:
        if not path:
            return ""
        return str(path).replace("/", "\\")

    @staticmethod
    def _resolve_folder_uid(
        raw_uid,
        local_uid_map: dict,
        *,
        invalid_as_none: bool,
    ) -> int | None:
        if not raw_uid:
            return None
        local_key = str(raw_uid)
        if local_key in local_uid_map:
            return int(local_uid_map[local_key])
        try:
            return int(raw_uid)
        except (TypeError, ValueError):
            if invalid_as_none:
                return None
            raise

    def save_cover_sheet(self, db_path: str, bid_uid: str, updates: dict) -> bool:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "Bids", ("UID",))
                cursor = conn.cursor()
                require_existing_unique_bid_owned_uid_matches(
                    cursor, "Bids", (bid_uid,)
                )
                existing_page_uids = list(updates.get("deleted_page_uids", []))
                existing_page_uids.extend(
                    page["uid"]
                    for page in updates.get("pages", [])
                    if page.get("uid") is not None
                )
                require_existing_bid_scoped_uid_matches(
                    cursor, "BidPages", existing_page_uids, int(bid_uid)
                )
                existing_folder_uids = list(updates.get("deleted_folder_uids", []))
                existing_folder_uids.extend(
                    folder["uid"]
                    for folder in updates.get("folders", [])
                    if folder.get("uid")
                )
                if existing_folder_uids and not schema.optional_table_missing(
                    "BidPageFolders"
                ):
                    require_unique_bid_owned_uid_matches(
                        cursor, "BidPageFolders", existing_folder_uids
                    )
                bid_uid_int = int(bid_uid)
                self._require_valid_cover_sheet_folder_updates(
                    cursor,
                    schema,
                    bid_uid_int,
                    updates,
                )
                new_mb = int(updates.get("measure_base", 0))
                old_mb = new_mb
                if schema.column_exists("Bids", "MeasureBase"):
                    cursor.execute(
                        "SELECT [MeasureBase] FROM [Bids] WHERE [UID]=?", bid_uid_int
                    )
                    row = cursor.fetchone()
                    old_mb = int(row[0] or 0) if row else new_mb
                notes = updates.get("notes", "") or ""
                notes = encode_text_blob(notes)
                job_status_uid = self._optional_integer(updates.get("job_status_uid"))
                estimator_uid = self._optional_integer(updates.get("estimator_uid"))
                master_reference_values: dict[str, object] = {}
                if schema.column_exists("Bids", "JobStatusUID"):
                    if schema.optional_table_missing("JobStatuses"):
                        if job_status_uid is not None:
                            raise RuntimeError(
                                "This OST database does not support Job Status "
                                "selection because JobStatuses is unavailable."
                            )
                    else:
                        if job_status_uid is not None:
                            require_existing_unique_master_data_uid(
                                cursor, "JobStatuses", job_status_uid
                            )
                        master_reference_values["JobStatusUID"] = job_status_uid
                if schema.column_exists("Bids", "EstimatorUID"):
                    if schema.optional_table_missing("Employees"):
                        if estimator_uid is not None:
                            raise RuntimeError(
                                "This OST database does not support Estimator "
                                "selection because Employees is unavailable."
                            )
                    else:
                        if estimator_uid is not None:
                            require_existing_unique_master_data_uid(
                                cursor, "Employees", estimator_uid
                            )
                        master_reference_values["EstimatorUID"] = estimator_uid
                bid_no = self._optional_integer(updates.get("bid_no"))
                bid_date = updates.get("bid_date")
                if bid_date in (None, ""):
                    bid_date = None
                self._execute_update_values(
                    cursor,
                    schema,
                    "Bids",
                    {
                        "JobName": updates.get("job_name", ""),
                        "Notes": notes,
                        "BidDate": bid_date,
                        "BidNo": bid_no,
                        "JobID": updates.get("job_id", ""),
                        "MeasureBase": new_mb,
                        "TakeoffIncrements": updates.get("takeoff_increments", 1.0),
                        "ScaleStyle": updates.get("scale_style", 1),
                        "ScaleFactor1": updates.get("scale_factor1", 0.25),
                        "ScaleFactor2": updates.get("scale_factor2", 12.0),
                        "PageWidth": updates.get("page_width", 42.0),
                        "PageHeight": updates.get("page_height", 30.0),
                        **master_reference_values,
                    },
                    ("UID", "JobName"),
                    "[UID]=?",
                    [bid_uid_int],
                    "save_cover_sheet_bid",
                )
                if old_mb != new_mb:
                    self._normalize_conditions_for_system(
                        cursor, bid_uid_int, metric=(new_mb == 1)
                    )
                for page_uid in updates.get("deleted_page_uids", []):
                    page_int = int(page_uid)
                    self._delete_page_cascade(cursor, schema, page_int)
                for folder_uid in updates.get("deleted_folder_uids", []):
                    if schema.column_exists("BidPages", "BidPageFolderUID"):
                        cursor.execute(
                            "UPDATE [BidPages] SET [BidPageFolderUID]=NULL WHERE [BidPageFolderUID]=?",
                            int(folder_uid),
                        )
                    if not schema.optional_table_missing("BidPageFolders"):
                        if schema.column_exists("BidPageFolders", "ParentUID"):
                            cursor.execute(
                                "UPDATE [BidPageFolders] SET [ParentUID]=NULL WHERE [ParentUID]=?",
                                int(folder_uid),
                            )
                        self._require_write_columns(schema, "BidPageFolders", ("UID",))
                        cursor.execute(
                            "DELETE FROM [BidPageFolders] WHERE [UID]=?",
                            int(folder_uid),
                        )
                local_uid_map: dict = {}
                for new_folder in updates.get("new_folders", []):
                    name = new_folder.get("name") or "New Folder"
                    parent_uid_val = self._resolve_folder_uid(
                        new_folder.get("parent_uid"),
                        local_uid_map,
                        invalid_as_none=True,
                    )
                    assigned_uid = self._next_uid_preserving_references(
                        cursor, schema, "BidPageFolders"
                    )
                    self._execute_insert_values(
                        cursor,
                        schema,
                        "BidPageFolders",
                        {
                            "UID": assigned_uid,
                            "BidUID": int(bid_uid),
                            "Name": name,
                            "ParentUID": parent_uid_val,
                        },
                        ("UID", "BidUID", "Name"),
                        "save_cover_sheet_new_folder",
                    )
                    local_uid = new_folder.get("local_uid")
                    if local_uid:
                        local_uid_map[str(local_uid)] = assigned_uid
                for folder in updates.get("folders", []):
                    if not folder.get("uid") or not folder.get("name"):
                        continue
                    parent_uid_val = self._resolve_folder_uid(
                        folder.get("parent_uid"),
                        local_uid_map,
                        invalid_as_none=False,
                    )
                    self._execute_update_values(
                        cursor,
                        schema,
                        "BidPageFolders",
                        {"Name": folder["name"], "ParentUID": parent_uid_val},
                        ("UID", "Name"),
                        "[UID]=?",
                        [int(folder["uid"])],
                        "save_cover_sheet_folder",
                    )
                for page in updates.get("pages", []):
                    if page.get("width") is None:
                        continue
                    if page.get("uid") is None:
                        folder_uid_val = self._resolve_folder_uid(
                            page.get("folder_uid"),
                            local_uid_map,
                            invalid_as_none=True,
                        )
                        new_guid = "{" + str(uuid.uuid4()).upper() + "}"
                        assigned_page_uid = self._next_uid_preserving_references(
                            cursor, schema, "BidPages"
                        )
                        overlay_values = replacement_overlay_storage_values(
                            self._windows_path_separators(page.get("overlay_path")),
                            page["width"],
                            page["height"],
                            page["scale_factor1"],
                            page["scale_factor2"],
                            original_image_path=page.get("image_path") or "",
                        )
                        self._execute_insert_values(
                            cursor,
                            schema,
                            "BidPages",
                            {
                                "UID": assigned_page_uid,
                                "BidUID": int(bid_uid),
                                "SheetNo": page.get("sheet_no") or "",
                                "Name": page.get("name") or "",
                                "Width": page["width"],
                                "Height": page["height"],
                                "ScaleFactor1": page["scale_factor1"],
                                "ScaleFactor2": page["scale_factor2"],
                                "Show": page["show_mode"],
                                "RasterDrawMethod": 1,
                                "ScaleStyle": 1,
                                "GUID": new_guid,
                                "Index1": page.get("index") or 1,
                                "Sequence": page.get("sequence") or 1,
                                "MultiPageCount": page.get("multi_page_count") or 0,
                                "ImagePath": self._windows_path_separators(
                                    page.get("image_path")
                                ),
                                **overlay_values,
                                "BidPageFolderUID": folder_uid_val,
                            },
                            ("UID", "BidUID"),
                            "save_cover_sheet_new_page",
                        )
                    else:
                        page_uid = int(page["uid"])
                        folder_uid_val = self._resolve_folder_uid(
                            page.get("folder_uid"),
                            local_uid_map,
                            invalid_as_none=False,
                        )
                        overlay_path = self._windows_path_separators(
                            page.get("overlay_path")
                        )
                        cursor.execute(
                            "SELECT [OverlayImagePath] FROM [BidPages] WHERE [UID]=?",
                            page_uid,
                        )
                        overlay_row = cursor.fetchone()
                        if overlay_row is None:
                            raise ValueError(f"Page {page_uid} does not exist")
                        overlay_replaced = overlay_path_storage_identity(
                            overlay_row[0]
                        ) != overlay_path_storage_identity(overlay_path)
                        overlay_values = {"OverlayImagePath": overlay_path}
                        if overlay_replaced:
                            overlay_values = replacement_overlay_storage_values(
                                overlay_path,
                                page["width"],
                                page["height"],
                                page["scale_factor1"],
                                page["scale_factor2"],
                                original_image_path=page.get("image_path") or "",
                            )
                        self._rescale_page_content_for_scale_change(
                            cursor,
                            schema,
                            page_uid,
                            page["scale_factor1"],
                            page["scale_factor2"],
                            rescale_overlay=not overlay_replaced,
                        )
                        self._execute_update_values(
                            cursor,
                            schema,
                            "BidPages",
                            {
                                "Width": page["width"],
                                "Height": page["height"],
                                "ScaleFactor1": page["scale_factor1"],
                                "ScaleFactor2": page["scale_factor2"],
                                "Show": page["show_mode"],
                                "SheetNo": page.get("sheet_no") or "",
                                "Index1": page.get("index") or 1,
                                "Name": page.get("name") or "",
                                "ImagePath": self._windows_path_separators(
                                    page.get("image_path")
                                ),
                                **overlay_values,
                                "BidPageFolderUID": folder_uid_val,
                                "Sequence": page.get("sequence") or 1,
                            },
                            ("UID",),
                            "[UID]=?",
                            [page_uid],
                            "save_cover_sheet_page",
                        )
                return True
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception(
                "Failed to save cover sheet for bid %s in %s", bid_uid, db_path
            )
            return False

    @staticmethod
    def _require_valid_cover_sheet_folder_updates(
        cursor,
        schema,
        bid_uid: int,
        updates: dict,
    ) -> None:
        folder_updates = list(updates.get("folders", []))
        new_folders = list(updates.get("new_folders", []))
        deleted_uids = list(updates.get("deleted_folder_uids", []))
        page_folder_uids = [
            page.get("folder_uid")
            for page in updates.get("pages", [])
            if page.get("folder_uid") not in (None, "", 0, "0")
        ]
        if (
            not folder_updates
            and not new_folders
            and not deleted_uids
            and not page_folder_uids
        ):
            return
        if schema.optional_table_missing("BidPageFolders"):
            raise RuntimeError(
                "This OST database does not support page-folder persistence."
            )
        has_parent_column = schema.column_exists("BidPageFolders", "ParentUID")
        if not has_parent_column and any(
            folder.get("parent_uid") not in (None, "", 0, "0")
            for folder in (*folder_updates, *new_folders)
        ):
            raise RuntimeError(
                "This OST database does not support page-folder hierarchy "
                "persistence."
            )
        schema.require_column("BidPageFolders", "UID")
        schema.require_column("BidPageFolders", "BidUID")
        parent_column = "[ParentUID]" if has_parent_column else "NULL AS [ParentUID]"
        cursor.execute(
            f"SELECT [UID], {parent_column} FROM [BidPageFolders] WHERE [BidUID]=?",
            bid_uid,
        )
        rows = cursor.fetchall()
        require_valid_unique_bid_owned_uids((row[0] for row in rows), "BidPageFolders")
        parent_by_uid: dict[str, object] = {str(int(row[0])): row[1] for row in rows}
        deleted = {str(int(uid)) for uid in deleted_uids}
        for uid in deleted:
            if uid not in parent_by_uid:
                raise MissingBidOwnedUidError(
                    f"BidPageFolders.UID={uid} does not belong to "
                    f"Bids.UID={bid_uid}."
                )
            del parent_by_uid[uid]
        for uid, parent_uid in tuple(parent_by_uid.items()):
            if parent_uid not in (None, "", 0, "0") and str(int(parent_uid)) in deleted:
                parent_by_uid[uid] = None
        local_uids: set[str] = set()
        for index, folder in enumerate(new_folders):
            local_uid = str(folder.get("local_uid") or f"__new_folder_{index}")
            if local_uid in local_uids or local_uid in parent_by_uid:
                raise RuntimeError(
                    f"BidPageFolders contains duplicate pending identity {local_uid}."
                )
            local_uids.add(local_uid)
            parent_by_uid[local_uid] = None

        def resolve_parent(raw_parent_uid) -> str | None:
            if raw_parent_uid in (None, "", 0, "0"):
                return None
            raw_key = str(raw_parent_uid)
            if raw_key in local_uids:
                return raw_key
            try:
                key = str(int(raw_parent_uid))
            except (TypeError, ValueError) as exc:
                raise MissingBidOwnedUidError(
                    f"BidPageFolders parent {raw_key} is not authoritative."
                ) from exc
            if key not in parent_by_uid:
                raise MissingBidOwnedUidError(
                    f"BidPageFolders.UID={key} does not belong to "
                    f"Bids.UID={bid_uid}."
                )
            return key

        for folder in folder_updates:
            uid = str(int(folder["uid"]))
            if uid not in parent_by_uid:
                raise MissingBidOwnedUidError(
                    f"BidPageFolders.UID={uid} does not belong to "
                    f"Bids.UID={bid_uid}."
                )
            parent_by_uid[uid] = resolve_parent(folder.get("parent_uid"))
        for index, folder in enumerate(new_folders):
            local_uid = str(folder.get("local_uid") or f"__new_folder_{index}")
            parent_by_uid[local_uid] = resolve_parent(folder.get("parent_uid"))
        for page_folder_uid in page_folder_uids:
            resolve_parent(page_folder_uid)
        if has_parent_column:
            require_acyclic_bid_owned_parent_graph(
                parent_by_uid,
                "BidPageFolders",
            )

    @staticmethod
    def _optional_integer(value) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            raise TypeError("Boolean values are not valid Access integer identifiers")
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            return int(stripped) if stripped else None
        raise TypeError(f"Unsupported Access integer value: {type(value).__name__}")

    def delete_pages(self, db_path: str, page_uids: list[str]) -> bool:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                cursor = conn.cursor()
                require_single_bid_scope_for_uids(cursor, "BidPages", page_uids)
                for page_uid in page_uids:
                    self._delete_page_cascade(cursor, schema, int(page_uid))
                return True
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception("Failed to delete pages in %s", db_path)
            return False

    def update_bid_job_status(
        self, db_path: str, bid_uid: str, job_status_uid: str | None
    ) -> bool:
        try:
            bid_uid_int = int(bid_uid)
            status_uid = self._optional_integer(job_status_uid)
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                cursor = conn.cursor()
                require_existing_unique_bid_owned_uid_matches(
                    cursor, "Bids", (bid_uid_int,)
                )
                if status_uid is not None and schema.column_exists(
                    "Bids", "JobStatusUID"
                ):
                    require_existing_unique_master_data_uid(
                        cursor, "JobStatuses", status_uid
                    )
                self._execute_update_values(
                    cursor,
                    schema,
                    "Bids",
                    {"JobStatusUID": status_uid},
                    ("UID", "JobStatusUID"),
                    "[UID]=?",
                    [bid_uid_int],
                    "update_bid_job_status",
                )
            return True
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception(
                "Failed to update job status for bid %s in %s", bid_uid, db_path
            )
            return False

    def _normalize_conditions_for_system(
        self, cursor, bid_uid_int: int, metric: bool
    ) -> None:
        schema = self._schema(cursor.connection)
        if schema.optional_table_missing("BidConditions"):
            return
        required = ("UID", "BidUID", "Name")
        if not all(
            schema.column_exists("BidConditions", column) for column in required
        ):
            return
        uom_columns = [
            column
            for column in ("UOM1", "UOM2", "UOM3")
            if schema.column_exists("BidConditions", column)
        ]
        select_columns = ["[UID]", "[Name]"] + [
            f"[{column}]"
            for column in ("UOM1", "UOM2", "UOM3")
            if column in uom_columns
        ]
        cursor.execute(
            f"SELECT {', '.join(select_columns)} "
            "FROM [BidConditions] WHERE [BidUID]=?",
            bid_uid_int,
        )
        rows = cursor.fetchall()
        for row in rows:
            row_data = dict(zip([c.strip("[]") for c in select_columns], row))
            uid = row_data["UID"]
            name = row_data["Name"]
            old_u1 = int(row_data.get("UOM1") or 0)
            old_u2 = int(row_data.get("UOM2") or 0)
            old_u3 = int(row_data.get("UOM3") or 0)
            new_u1 = normalize_uom_for_system(old_u1, metric)
            new_u2 = normalize_uom_for_system(old_u2, metric)
            new_u3 = normalize_uom_for_system(old_u3, metric)
            uom_values = {}
            if "UOM1" in uom_columns and new_u1 != old_u1:
                uom_values["UOM1"] = new_u1
            if "UOM2" in uom_columns and new_u2 != old_u2:
                uom_values["UOM2"] = new_u2
            if "UOM3" in uom_columns and new_u3 != old_u3:
                uom_values["UOM3"] = new_u3
            new_name = convert_elevation_in_name(name or "", metric)
            name_changed = bool(name) and new_name != name
            if not uom_values and not name_changed:
                continue
            values = dict(uom_values)
            if name_changed:
                values["Name"] = new_name
            self._execute_update_values(
                cursor,
                schema,
                "BidConditions",
                values,
                ("UID", "BidUID"),
                "[UID]=? AND [BidUID]=?",
                [int(uid), bid_uid_int],
                "normalize_conditions_for_system",
            )

    def _delete_page_cascade(self, cursor, schema, page_int: int) -> None:
        page_bid_uid = None
        if schema.column_exists("BidPages", "BidUID"):
            cursor.execute("SELECT [BidUID] FROM [BidPages] WHERE [UID]=?", page_int)
            page_row = cursor.fetchone()
            if page_row is not None:
                page_bid_uid = page_row[0]
        if page_bid_uid is not None and schema.column_exists(
            "BidPages", "MasterPageUID"
        ):
            cursor.execute(
                "UPDATE [BidPages] SET [MasterPageUID]=NULL "
                "WHERE [BidUID]=? AND [MasterPageUID]=?",
                page_bid_uid,
                page_int,
            )
        if (
            page_bid_uid is not None
            and not schema.optional_table_missing("BidComments")
            and all(
                schema.column_exists("BidComments", column)
                for column in ("UID", "BidUID", "BidPageUID", "ParentCommentUID")
            )
        ):
            cursor.execute(
                "SELECT [UID] FROM [BidComments] "
                "WHERE [BidUID]=? AND [BidPageUID]=?",
                page_bid_uid,
                page_int,
            )
            deleted_comment_rows = cursor.fetchall()
            require_valid_unique_bid_owned_uids(
                (row[0] for row in deleted_comment_rows), "BidComments"
            )
            deleted_comment_uids = [int(row[0]) for row in deleted_comment_rows]
            if deleted_comment_uids:
                placeholders = ",".join("?" for _uid in deleted_comment_uids)
                cursor.execute(
                    "UPDATE [BidComments] SET [ParentCommentUID]=NULL "
                    f"WHERE [BidUID]=? AND [ParentCommentUID] IN ({placeholders})",
                    page_bid_uid,
                    *deleted_comment_uids,
                )
        if (
            page_bid_uid is not None
            and not schema.optional_table_missing("BidTakeoffs")
            and all(
                schema.column_exists("BidTakeoffs", column)
                for column in ("UID", "BidUID", "BidPageUID")
            )
        ):
            cursor.execute(
                "SELECT [UID] FROM [BidTakeoffs] "
                "WHERE [BidUID]=? AND [BidPageUID]=?",
                page_bid_uid,
                page_int,
            )
            deleted_takeoff_rows = cursor.fetchall()
            require_valid_unique_bid_owned_uids(
                (row[0] for row in deleted_takeoff_rows), "BidTakeoffs"
            )
            deleted_takeoff_uids = [int(row[0]) for row in deleted_takeoff_rows]
            for reference_column in TAKEOFF_SELF_REFERENCE_COLUMNS:
                if not schema.column_exists("BidTakeoffs", reference_column):
                    continue
                for uid_chunk in self._iter_access_chunks(deleted_takeoff_uids):
                    where_sql, where_params = self._uid_where_clause(
                        reference_column, uid_chunk
                    )
                    cursor.execute(
                        f"UPDATE [BidTakeoffs] SET [{reference_column}]=NULL "
                        f"WHERE [BidUID]=? AND {where_sql}",
                        page_bid_uid,
                        *where_params,
                    )
        if (
            not schema.optional_table_missing("BidPercents")
            and not schema.optional_table_missing("BidTakeoffs")
            and schema.column_exists("BidPercents", "BidTakeoffUID")
            and schema.column_exists("BidTakeoffs", "UID")
            and schema.column_exists("BidTakeoffs", "BidPageUID")
        ):
            cursor.execute(
                "DELETE FROM [BidPercents] WHERE [BidTakeoffUID] IN "
                "(SELECT [UID] FROM [BidTakeoffs] WHERE [BidPageUID] = ?)",
                page_int,
            )
        for child in TAKEOFF_REFERENCE_TABLES:
            if (
                schema.optional_table_missing(child)
                or schema.optional_table_missing("BidTakeoffs")
                or not schema.column_exists("BidTakeoffs", "UID")
                or not schema.column_exists("BidTakeoffs", "BidPageUID")
            ):
                continue
            for reference_column in TAKEOFF_ANNOTATION_REFERENCE_COLUMNS:
                if not schema.column_exists(child, reference_column):
                    continue
                cursor.execute(
                    f"DELETE FROM [{child}] WHERE [{reference_column}] IN "
                    "(SELECT [UID] FROM [BidTakeoffs] WHERE [BidPageUID] = ?)",
                    page_int,
                )
        if (
            not schema.optional_table_missing("AffectDPCTypGroupViews")
            and not schema.optional_table_missing("BidTypGroupViews")
            and schema.column_exists("AffectDPCTypGroupViews", "BidTypGroupViewUID")
            and schema.column_exists("BidTypGroupViews", "UID")
            and schema.column_exists("BidTypGroupViews", "BidPageUID")
        ):
            cursor.execute(
                "DELETE FROM [AffectDPCTypGroupViews] "
                "WHERE [BidTypGroupViewUID] IN "
                "(SELECT [UID] FROM [BidTypGroupViews] WHERE [BidPageUID]=?)",
                page_int,
            )
        for table in PAGE_DELETE_CHILD_TABLES:
            try:
                if schema.optional_table_missing(table) or not schema.column_exists(
                    table, "BidPageUID"
                ):
                    continue
                cursor.execute(
                    f"DELETE FROM [{table}] WHERE [BidPageUID] = ?", page_int
                )
            except pyodbc.Error as exc:
                if self._record_caught_mutation_error(exc):
                    raise
                self.logger.warning(
                    "Failed to delete from %s for page %s: %s", table, page_int, exc
                )
        if not schema.optional_table_missing("BidTakeoffs") and schema.column_exists(
            "BidTakeoffs", "BidPageUID"
        ):
            cursor.execute("DELETE FROM [BidTakeoffs] WHERE [BidPageUID] = ?", page_int)
        if (
            not schema.optional_table_missing("BidHotLinks")
            and not schema.optional_table_missing("BidNamedViews")
            and schema.column_exists("BidHotLinks", "BidPageViewUID")
            and schema.column_exists("BidNamedViews", "UID")
            and schema.column_exists("BidNamedViews", "BidPageUID")
        ):
            cursor.execute(
                "DELETE FROM [BidHotLinks] WHERE [BidPageViewUID] IN "
                "(SELECT [UID] FROM [BidNamedViews] WHERE [BidPageUID] = ?)",
                page_int,
            )
        if not schema.optional_table_missing("BidHotLinks") and schema.column_exists(
            "BidHotLinks", "BidPageUID"
        ):
            cursor.execute("DELETE FROM [BidHotLinks] WHERE [BidPageUID] = ?", page_int)
        if not schema.optional_table_missing("BidNamedViews") and schema.column_exists(
            "BidNamedViews", "BidPageUID"
        ):
            cursor.execute(
                "DELETE FROM [BidNamedViews] WHERE [BidPageUID] = ?", page_int
            )
        if not schema.optional_table_missing("BidSettings") and schema.column_exists(
            "BidSettings", "BidPageSelectedUID"
        ):
            cursor.execute(
                "UPDATE [BidSettings] SET [BidPageSelectedUID]=NULL "
                "WHERE [BidPageSelectedUID]=?",
                page_int,
            )
        if all(
            schema.column_exists("Bids", column)
            for column in ("CoverSheetSelItemType", "CoverSheetSelItemUID")
        ):
            cursor.execute(
                "UPDATE [Bids] SET [CoverSheetSelItemUID]=NULL "
                "WHERE [CoverSheetSelItemType]=? AND [CoverSheetSelItemUID]=?",
                COVER_SHEET_PAGE_SELECTION_TYPE,
                page_int,
            )
        self._require_write_columns(schema, "BidPages", ("UID",))
        cursor.execute("DELETE FROM [BidPages] WHERE [UID]=?", page_int)

    def save_job_statuses(
        self, db_path: str, changes: Dict[str, Any]
    ) -> Optional[Dict[str, str]]:
        uid_map: dict[str, str] = {}
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                if schema.optional_table_missing("JobStatuses"):
                    raise RuntimeError(
                        "This OST database does not support job statuses."
                    )
                cursor = conn.cursor()
                self._require_write_columns(schema, "JobStatuses", ("UID",))
                for uid in changes.get("deleted_uids", []):
                    try:
                        uid_int = int(uid)
                        _require_unique_master_data_row(cursor, "JobStatuses", uid_int)
                        if not schema.optional_table_missing(
                            "Bids"
                        ) and schema.column_exists("Bids", "JobStatusUID"):
                            cursor.execute(
                                "UPDATE [Bids] SET [JobStatusUID]=NULL WHERE [JobStatusUID]=?",
                                uid_int,
                            )
                        cursor.execute(
                            "DELETE FROM [JobStatuses] WHERE [UID]=?", uid_int
                        )
                    except (pyodbc.Error, ValueError) as exc:
                        if self._record_caught_mutation_error(exc):
                            raise
                for s in changes.get("updated", []):
                    uid = s.get("uid")
                    if uid is None:
                        continue
                    try:
                        uid_int = int(uid)
                        _require_unique_master_data_row(cursor, "JobStatuses", uid_int)
                        locked_val = -1 if s.get("locked") else 0
                        self._execute_update_values(
                            cursor,
                            schema,
                            "JobStatuses",
                            {
                                "Name": s.get("name", ""),
                                "Locked": locked_val,
                                "Sequence": s.get("sequence", 0),
                            },
                            ("UID", "Name"),
                            "[UID]=?",
                            [uid_int],
                            "save_job_status",
                        )
                    except (pyodbc.Error, ValueError) as exc:
                        if self._record_caught_mutation_error(exc):
                            raise
                for s in changes.get("new", []):
                    try:
                        locked_val = -1 if s.get("locked") else 0
                        assigned_uid = self._next_uid_preserving_references(
                            cursor, schema, "JobStatuses"
                        )
                        self._execute_insert_values(
                            cursor,
                            schema,
                            "JobStatuses",
                            {
                                "UID": assigned_uid,
                                "Name": s.get("name", "New Status"),
                                "Locked": locked_val,
                                "Sequence": s.get("sequence", 0),
                            },
                            ("UID", "Name"),
                            "save_job_status_new",
                        )
                        uid_map[str(s.get("uid", ""))] = str(assigned_uid)
                    except pyodbc.Error as exc:
                        if self._record_caught_mutation_error(exc):
                            raise
                return uid_map
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception("Failed to save job statuses in %s", db_path)
            return None

    def save_employees(self, db_path: str, changes: dict) -> dict | None:
        uid_map: dict = {}
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                if schema.optional_table_missing("Employees"):
                    raise RuntimeError("This OST database does not support employees.")
                cursor = conn.cursor()
                self._require_write_columns(schema, "Employees", ("UID",))
                employee_changes = [
                    *changes.get("updated", []),
                    *changes.get("new", []),
                ]
                pay_class_uids = {
                    int(employee.pay_class_uid)
                    for employee in employee_changes
                    if employee.pay_class_uid
                    and not str(employee.pay_class_uid).startswith("new_")
                }
                for pay_class_uid in sorted(pay_class_uids):
                    require_existing_unique_master_data_uid(
                        cursor, "PayClasses", pay_class_uid
                    )
                for uid in changes.get("deleted_uids", []):
                    try:
                        uid_int = int(uid)
                        _require_unique_master_data_row(cursor, "Employees", uid_int)
                        if not schema.optional_table_missing("Bids"):
                            for role_column in (
                                "EstimatorUID",
                                "PrManagerUID",
                                "JobSiteManagerUID",
                            ):
                                if schema.column_exists("Bids", role_column):
                                    cursor.execute(
                                        f"UPDATE [Bids] SET [{role_column}]=NULL "
                                        f"WHERE [{role_column}]=?",
                                        uid_int,
                                    )
                        if not schema.optional_table_missing(
                            "BidDPCSubscribers"
                        ) and schema.column_exists(
                            "BidDPCSubscribers", "BidEmployeeUID"
                        ):
                            cursor.execute(
                                "DELETE FROM [BidDPCSubscribers] "
                                "WHERE [BidEmployeeUID]=?",
                                uid_int,
                            )
                        if (
                            not schema.optional_table_missing("BidTimeCards")
                            and not schema.optional_table_missing("BidEmployees")
                            and schema.column_exists("BidTimeCards", "BidEmployeeUID")
                            and schema.column_exists("BidEmployees", "UID")
                            and schema.column_exists("BidEmployees", "EmployeeUID")
                        ):
                            cursor.execute(
                                "DELETE FROM [BidTimeCards] WHERE [BidEmployeeUID] IN "
                                "(SELECT [UID] FROM [BidEmployees] WHERE [EmployeeUID]=?)",
                                uid_int,
                            )
                        if not schema.optional_table_missing(
                            "BidEmployees"
                        ) and schema.column_exists("BidEmployees", "EmployeeUID"):
                            cursor.execute(
                                "DELETE FROM [BidEmployees] WHERE [EmployeeUID]=?",
                                uid_int,
                            )
                        try:
                            if not schema.optional_table_missing(
                                "ConditionSets"
                            ) and schema.column_exists("ConditionSets", "EmployeeUID"):
                                cursor.execute(
                                    "UPDATE [ConditionSets] SET [EmployeeUID]=NULL "
                                    "WHERE [EmployeeUID]=?",
                                    uid_int,
                                )
                        except pyodbc.Error as exc:
                            if self._record_caught_mutation_error(exc):
                                raise
                            self.logger.warning(
                                "Failed to clear ConditionSets.EmployeeUID for %s: %s",
                                uid_int,
                                exc,
                            )
                        cursor.execute("DELETE FROM [Employees] WHERE [UID]=?", uid_int)
                    except (pyodbc.Error, ValueError) as exc:
                        if self._record_caught_mutation_error(exc):
                            raise
                        self.logger.warning(
                            "Failed to delete employee %s: %s", uid, exc
                        )
                for e in changes.get("updated", []):
                    uid = e.uid
                    if uid is None:
                        continue
                    try:
                        uid_int = int(uid)
                        _require_unique_master_data_row(cursor, "Employees", uid_int)
                        raw_pc_uid = e.pay_class_uid
                        pc_uid_val = (
                            int(raw_pc_uid)
                            if raw_pc_uid and not str(raw_pc_uid).startswith("new_")
                            else None
                        )
                        self._execute_update_values(
                            cursor,
                            schema,
                            "Employees",
                            {
                                "EmployeeNo": e.employee_no,
                                "FirstName": e.first_name,
                                "LastName": e.last_name,
                                "Address1": e.address1,
                                "Address2": e.address2,
                                "City": e.city,
                                "State": e.state,
                                "Zip": e.zip,
                                "HomePhone": e.home_phone,
                                "MobilePhone": e.mobile_phone,
                                "EMail": e.email,
                                "PayClassUID": pc_uid_val,
                            },
                            ("UID",),
                            "[UID]=?",
                            [uid_int],
                            "save_employee",
                        )
                    except (pyodbc.Error, ValueError) as exc:
                        if self._record_caught_mutation_error(exc):
                            raise
                for e in changes.get("new", []):
                    try:
                        raw_pc_uid = e.pay_class_uid
                        pc_uid_val = (
                            int(raw_pc_uid)
                            if raw_pc_uid and not str(raw_pc_uid).startswith("new_")
                            else None
                        )
                        assigned_uid = self._next_uid_preserving_references(
                            cursor, schema, "Employees"
                        )
                        self._execute_insert_values(
                            cursor,
                            schema,
                            "Employees",
                            {
                                "UID": assigned_uid,
                                "EmployeeNo": e.employee_no,
                                "FirstName": e.first_name,
                                "LastName": e.last_name,
                                "Address1": e.address1,
                                "Address2": e.address2,
                                "City": e.city,
                                "State": e.state,
                                "Zip": e.zip,
                                "HomePhone": e.home_phone,
                                "MobilePhone": e.mobile_phone,
                                "EMail": e.email,
                                "PayClassUID": pc_uid_val,
                            },
                            ("UID",),
                            "save_employee_new",
                        )
                        uid_map[str(e.uid)] = str(assigned_uid)
                    except (pyodbc.Error, ValueError) as exc:
                        if self._record_caught_mutation_error(exc):
                            raise
                return uid_map
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception("Failed to save employees in %s", db_path)
            return None

    def save_pay_classes(
        self, db_path: str, changes: Dict[str, Any]
    ) -> Optional[Dict[str, str]]:
        uid_map: dict[str, str] = {}
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                if schema.optional_table_missing("PayClasses"):
                    raise RuntimeError(
                        "This OST database does not support pay classes."
                    )
                cursor = conn.cursor()
                self._require_write_columns(schema, "PayClasses", ("UID",))
                for uid in changes.get("deleted_uids", []):
                    try:
                        uid_int = int(uid)
                        _require_unique_master_data_row(cursor, "PayClasses", uid_int)
                        if not schema.optional_table_missing(
                            "Employees"
                        ) and schema.column_exists("Employees", "PayClassUID"):
                            cursor.execute(
                                "UPDATE [Employees] SET [PayClassUID]=NULL WHERE [PayClassUID]=?",
                                uid_int,
                            )
                        if not schema.optional_table_missing(
                            "BidEmployees"
                        ) and schema.column_exists("BidEmployees", "PayClassUID"):
                            cursor.execute(
                                "UPDATE [BidEmployees] SET [PayClassUID]=NULL "
                                "WHERE [PayClassUID]=?",
                                uid_int,
                            )
                        cursor.execute(
                            "DELETE FROM [PayClasses] WHERE [UID]=?", uid_int
                        )
                    except (pyodbc.Error, ValueError) as exc:
                        if self._record_caught_mutation_error(exc):
                            raise
                        self.logger.warning(
                            "Failed to delete pay class %s: %s", uid, exc
                        )
                for pc in changes.get("updated", []):
                    uid = pc.get("uid")
                    if uid is None:
                        continue
                    try:
                        uid_int = int(uid)
                        _require_unique_master_data_row(cursor, "PayClasses", uid_int)
                        self._execute_update_values(
                            cursor,
                            schema,
                            "PayClasses",
                            {"Name": pc.get("name", "")},
                            ("UID", "Name"),
                            "[UID]=?",
                            [uid_int],
                            "save_pay_class",
                        )
                    except (pyodbc.Error, ValueError) as exc:
                        if self._record_caught_mutation_error(exc):
                            raise
                for pc in changes.get("new", []):
                    try:
                        assigned_uid = self._next_uid_preserving_references(
                            cursor, schema, "PayClasses"
                        )
                        self._execute_insert_values(
                            cursor,
                            schema,
                            "PayClasses",
                            {
                                "UID": assigned_uid,
                                "Name": pc.get("name", "New Pay Class"),
                            },
                            ("UID", "Name"),
                            "save_pay_class_new",
                        )
                        uid_map[str(pc.get("uid", ""))] = str(assigned_uid)
                    except pyodbc.Error as exc:
                        if self._record_caught_mutation_error(exc):
                            raise
                return uid_map
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception("Failed to save pay classes in %s", db_path)
            return None

    def save_condition_types(self, db_path: str, changes: dict) -> dict | None:
        uid_map: dict = {}
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                if schema.optional_table_missing("CdnTypes"):
                    raise RuntimeError(
                        "This OST database does not support condition types."
                    )
                cursor = conn.cursor()
                self._require_write_columns(schema, "CdnTypes", ("UID",))
                deletion_uids = []
                for uid in changes.get("deleted_uids", []):
                    try:
                        deletion_uids.append((uid, int(uid)))
                    except ValueError as exc:
                        if self._record_caught_mutation_error(exc):
                            raise
                        self.logger.warning(
                            "Failed to delete condition type %s: %s", uid, exc
                        )
                for _uid, uid_int in deletion_uids:
                    _require_unique_master_data_row(cursor, "CdnTypes", uid_int)
                if not schema.optional_table_missing(
                    "BidConditions"
                ) and schema.column_exists("BidConditions", "CdnTypeUID"):
                    for _uid, uid_int in deletion_uids:
                        try:
                            cursor.execute(
                                "SELECT COUNT(*) FROM [BidConditions] "
                                "WHERE [CdnTypeUID]=?",
                                uid_int,
                            )
                            row = cursor.fetchone()
                            if row and int(row[0] or 0) > 0:
                                self.logger.warning(
                                    "Refusing to delete condition type in use: %s",
                                    uid_int,
                                )
                                return None
                        except pyodbc.Error as exc:
                            if self._record_caught_mutation_error(exc):
                                raise
                            self.logger.warning(
                                "Failed to validate condition type %s usage: %s",
                                uid_int,
                                exc,
                            )
                            return None
                for uid, uid_int in deletion_uids:
                    try:
                        cursor.execute("DELETE FROM [CdnTypes] WHERE [UID]=?", uid_int)
                    except pyodbc.Error as exc:
                        if self._record_caught_mutation_error(exc):
                            raise
                        self.logger.warning(
                            "Failed to delete condition type %s: %s", uid, exc
                        )
                for item in changes.get("updated", []):
                    uid = item.get("uid")
                    if uid is None:
                        continue
                    try:
                        uid_int = int(uid)
                        _require_unique_master_data_row(cursor, "CdnTypes", uid_int)
                        self._execute_update_values(
                            cursor,
                            schema,
                            "CdnTypes",
                            {"Name": item.get("name", "")},
                            ("UID", "Name"),
                            "[UID]=?",
                            [uid_int],
                            "save_condition_type",
                        )
                    except (pyodbc.Error, ValueError) as exc:
                        if self._record_caught_mutation_error(exc):
                            raise
                for item in changes.get("new", []):
                    temp_uid = str(item.get("uid", ""))
                    try:
                        assigned_uid = self._next_uid_preserving_references(
                            cursor, schema, "CdnTypes"
                        )
                        self._execute_insert_values(
                            cursor,
                            schema,
                            "CdnTypes",
                            {
                                "UID": assigned_uid,
                                "Name": item.get("name", "New Condition Type"),
                            },
                            ("UID", "Name"),
                            "save_condition_type_new",
                        )
                        uid_map[temp_uid] = str(assigned_uid)
                    except pyodbc.Error as exc:
                        if self._record_caught_mutation_error(exc):
                            raise
                return uid_map
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception("Failed to save condition types in %s", db_path)
            return None

    @staticmethod
    def _require_valid_bid_area_changes(
        cursor,
        schema,
        bid_uid: int,
        changes: BidAreaChangeset,
    ) -> None:
        schema.require_column("BidAreas", "UID")
        schema.require_column("BidAreas", "BidUID")
        has_parent_column = schema.column_exists("BidAreas", "ParentUID")
        parent_column = "[ParentUID]" if has_parent_column else "NULL AS [ParentUID]"
        cursor.execute(
            f"SELECT [UID], {parent_column} FROM [BidAreas] WHERE [BidUID]=?",
            bid_uid,
        )
        rows = cursor.fetchall()
        require_valid_unique_bid_owned_uids((row[0] for row in rows), "BidAreas")
        existing_parent_by_uid = {
            str(int(row[0])): (
                None if row[1] in (None, "", 0, "0") else str(int(row[1]))
            )
            for row in rows
        }
        deleted_uids = [str(uid) for uid in changes.deleted_uids]
        updated_uids = [str(area.uid) for area in changes.updated]
        require_valid_unique_bid_owned_uids(deleted_uids, "BidAreas")
        require_valid_unique_bid_owned_uids(updated_uids, "BidAreas")
        deleted = {str(int(uid)) for uid in deleted_uids}
        updated = {str(int(uid)) for uid in updated_uids}
        overlap = deleted & updated
        if overlap:
            uid = min(overlap, key=int)
            raise RuntimeError(
                f"BidAreas.UID={uid} cannot be updated and deleted in one save."
            )
        missing_targets = (deleted | updated) - set(existing_parent_by_uid)
        if missing_targets:
            uid = min(missing_targets, key=int)
            raise MissingBidOwnedUidError(
                f"BidAreas.UID={uid} does not belong to Bids.UID={bid_uid}."
            )
        pending_uids: set[str] = set()
        for area in changes.new:
            local_uid = str(area.uid)
            if (
                not local_uid
                or local_uid in pending_uids
                or local_uid in existing_parent_by_uid
            ):
                raise RuntimeError(
                    "BidAreas contains duplicate pending identity "
                    f"{local_uid or '<missing>'}."
                )
            pending_uids.add(local_uid)
        final_parent_by_uid = {
            uid: parent_uid
            for uid, parent_uid in existing_parent_by_uid.items()
            if uid not in deleted
        }
        final_parent_by_uid.update({uid: None for uid in pending_uids})

        def resolve_parent(raw_parent_uid, child_uid: str) -> str | None:
            if raw_parent_uid in (None, "", 0, "0"):
                return None
            raw_key = str(raw_parent_uid)
            if raw_key in pending_uids:
                parent_uid = raw_key
            else:
                try:
                    parent_uid = str(int(raw_parent_uid))
                except (TypeError, ValueError) as exc:
                    raise MissingBidOwnedUidError(
                        f"BidAreas.UID={child_uid} has a non-authoritative "
                        f"ParentUID {raw_key}."
                    ) from exc
            if parent_uid not in final_parent_by_uid:
                raise DanglingBidOwnedReferenceError(
                    f"BidAreas.UID={child_uid} references missing "
                    f"BidAreas.UID={parent_uid} through ParentUID."
                )
            return parent_uid

        for area in changes.updated:
            uid = str(int(area.uid))
            final_parent_by_uid[uid] = resolve_parent(area.parent_uid, uid)
        for area in changes.new:
            uid = str(area.uid)
            final_parent_by_uid[uid] = resolve_parent(area.parent_uid, uid)
        for uid, parent_uid in tuple(final_parent_by_uid.items()):
            final_parent_by_uid[uid] = resolve_parent(parent_uid, uid)
        if not has_parent_column and any(
            parent_uid is not None for parent_uid in final_parent_by_uid.values()
        ):
            raise RuntimeError(
                "This OST database does not support Bid Area hierarchy persistence."
            )
        require_acyclic_bid_owned_parent_graph(final_parent_by_uid, "BidAreas")

    def save_bid_areas(
        self, db_path: str, bid_uid: str, changes: BidAreaChangeset
    ) -> dict:
        uid_map: dict = {}
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                if schema.optional_table_missing("BidAreas"):
                    raise RuntimeError("This OST database does not support bid areas.")
                cursor = conn.cursor()
                require_existing_unique_bid_owned_uid_matches(
                    cursor, "Bids", (bid_uid,)
                )
                self._require_valid_bid_area_changes(
                    cursor,
                    schema,
                    int(bid_uid),
                    changes,
                )
                existing_area_uids = list(changes.deleted_uids)
                existing_area_uids.extend(area.uid for area in changes.updated)
                require_unique_bid_owned_uid_matches(
                    cursor, "BidAreas", existing_area_uids
                )
                for uid in changes.deleted_uids:
                    try:
                        uid_int = int(uid)
                        if not schema.optional_table_missing(
                            "BidPageSettings"
                        ) and schema.column_exists("BidPageSettings", "BidAreaUID"):
                            cursor.execute(
                                "UPDATE [BidPageSettings] SET [BidAreaUID]=NULL WHERE [BidAreaUID]=?",
                                uid_int,
                            )
                        if not schema.optional_table_missing(
                            "BidTakeoffs"
                        ) and schema.column_exists("BidTakeoffs", "BidAreaUID"):
                            cursor.execute(
                                "UPDATE [BidTakeoffs] SET [BidAreaUID]=NULL WHERE [BidAreaUID]=?",
                                uid_int,
                            )
                        if not schema.optional_table_missing("BidAreaTranslations"):
                            translation_columns = tuple(
                                column
                                for column in ("MasterAreaUID", "TranslateAreaUID")
                                if schema.column_exists("BidAreaTranslations", column)
                            )
                        else:
                            translation_columns = ()
                        if translation_columns:
                            cursor.execute(
                                "DELETE FROM [BidAreaTranslations] "
                                "WHERE "
                                + " OR ".join(
                                    f"[{column}]=?" for column in translation_columns
                                ),
                                *(uid_int for _column in translation_columns),
                            )
                        for table in (
                            "BidTakeoffTotals",
                            "BidLaborCostCodeTotals",
                            "BidTypicalGroupTotals",
                        ):
                            if schema.optional_table_missing(
                                table
                            ) or not schema.column_exists(table, "BidAreaUID"):
                                continue
                            cursor.execute(
                                f"DELETE FROM [{table}] WHERE [BidAreaUID]=?",
                                uid_int,
                            )
                        try:
                            if not schema.optional_table_missing(
                                "BidTimeCards"
                            ) and schema.column_exists("BidTimeCards", "BidAreaUID"):
                                cursor.execute(
                                    "DELETE FROM [BidTimeCards] WHERE [BidAreaUID]=?",
                                    uid_int,
                                )
                        except pyodbc.Error as exc:
                            if self._record_caught_mutation_error(exc):
                                raise
                        try:
                            if not schema.optional_table_missing(
                                "BidTypAreaCounts"
                            ) and schema.column_exists(
                                "BidTypAreaCounts", "BidAreaUID"
                            ):
                                cursor.execute(
                                    "DELETE FROM [BidTypAreaCounts] WHERE [BidAreaUID]=?",
                                    uid_int,
                                )
                        except pyodbc.Error as exc:
                            if self._record_caught_mutation_error(exc):
                                raise
                        self._require_write_columns(schema, "BidAreas", ("UID",))
                        cursor.execute("DELETE FROM [BidAreas] WHERE [UID]=?", uid_int)
                    except (pyodbc.Error, ValueError) as exc:
                        if self._record_caught_mutation_error(exc):
                            raise
                for area in changes.new:
                    try:
                        if area.parent_uid and area.parent_uid in uid_map:
                            parent_val = int(uid_map[area.parent_uid])
                        elif area.parent_uid and not area.parent_uid.startswith("new_"):
                            parent_val = int(area.parent_uid)
                        else:
                            parent_val = None
                        new_guid = "{" + str(uuid.uuid4()).upper() + "}"
                        assigned_uid = self._next_uid_preserving_references(
                            cursor, schema, "BidAreas"
                        )
                        self._execute_insert_values(
                            cursor,
                            schema,
                            "BidAreas",
                            {
                                "UID": assigned_uid,
                                "BidUID": int(bid_uid),
                                "ParentUID": parent_val,
                                "Name": area.name,
                                "Sequence": area.sequence,
                                "WasSent": 0,
                                "GUID": new_guid,
                            },
                            ("UID", "BidUID", "Name"),
                            "save_bid_area_new",
                        )
                        uid_map[area.uid] = str(assigned_uid)
                    except pyodbc.Error as exc:
                        if self._record_caught_mutation_error(exc):
                            raise
                for area in changes.updated:
                    try:
                        raw_parent_uid = uid_map.get(area.parent_uid, area.parent_uid)
                        parent_val = int(raw_parent_uid) if raw_parent_uid else None
                        self._execute_update_values(
                            cursor,
                            schema,
                            "BidAreas",
                            {
                                "Name": area.name,
                                "ParentUID": parent_val,
                                "Sequence": area.sequence,
                            },
                            ("UID", "Name"),
                            "[UID]=?",
                            [int(area.uid)],
                            "save_bid_area",
                        )
                    except (pyodbc.Error, ValueError) as exc:
                        if self._record_caught_mutation_error(exc):
                            raise
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception(
                "Failed to save bid areas for bid %s in %s", bid_uid, db_path
            )
        return uid_map

    def save_bid_selected_page(self, db_path: str, bid_uid: str, page_uid: str) -> bool:
        try:
            page_val = int(page_uid) if page_uid else None
        except ValueError:
            page_val = None
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                if schema.optional_table_missing("BidSettings"):
                    raise RuntimeError(
                        "This OST database does not support selected page persistence."
                    )
                self._require_write_columns(
                    schema, "BidSettings", ("BidUID", "BidPageSelectedUID")
                )
                cursor = conn.cursor()
                require_existing_unique_bid_owned_uid_matches(
                    cursor, "Bids", (bid_uid,)
                )
                fetch_optional_bid_settings_row(cursor, int(bid_uid), ("BidUID",))
                if page_val is not None:
                    self._require_write_columns(schema, "BidPages", ("UID", "BidUID"))
                    cursor.execute(
                        "SELECT UID FROM [BidPages] WHERE UID=? AND BidUID=?",
                        page_val,
                        int(bid_uid),
                    )
                    if cursor.fetchone() is None:
                        return False
                cursor.execute(
                    "UPDATE [BidSettings] SET [BidPageSelectedUID]=? WHERE [BidUID]=?",
                    page_val,
                    int(bid_uid),
                )
                if cursor.rowcount == 0:
                    self._execute_insert_values(
                        cursor,
                        schema,
                        "BidSettings",
                        {"BidUID": int(bid_uid), "BidPageSelectedUID": page_val},
                        ("BidUID", "BidPageSelectedUID"),
                        "save_bid_selected_page",
                    )
                return True
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception(
                "Failed to save bid selected page for bid %s in %s",
                bid_uid,
                db_path,
            )
            return False
