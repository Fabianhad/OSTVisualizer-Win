import datetime
import uuid
from typing import Dict, List, Optional
import pyodbc
from ...database.settings_cardinality import (
    fetch_optional_global_settings_row,
    normalize_next_bid_number,
    persist_next_bid_number,
    require_writable_bid_number_allocator,
)
from ...database.page_area_selection import canonicalize_page_area_settings
from ...database.master_data_identity import (
    require_optional_existing_unique_master_data_uid,
)
from ...database.bid_owned_identity import (
    DanglingBidOwnedReferenceError,
    require_acyclic_bid_owned_parent_graph,
    require_existing_unique_bid_owned_uid_matches,
    require_unique_bid_owned_uid_matches,
    require_valid_unique_bid_owned_uids,
)
from ..bid_settings_contract import fetch_optional_bid_settings_row
from ..schema_contract import BID_SECTIONS, BID_TAIL_SECTIONS, PAGE_SECTIONS
from .constants import (
    COVER_SHEET_PAGE_SELECTION_TYPE,
    HANDLED_SEPARATELY,
    LEGACY_BID_TABLES_COPIED_BY_DUPLICATION,
    PAGE_DELETE_CHILD_TABLES,
    TAKEOFF_ANNOTATION_REFERENCE_COLUMNS,
    TAKEOFF_REFERENCE_TABLES,
)
from ..raw_bid_integrity import BID_RELATIONSHIPS
from .serialization import coerce_binary_column_value, encode_text_blob
from .identity_allocation import AccessIdentityAllocationMixin
from .sql_helpers import placeholders

_BID_SCOPED_PRE = (
    "BidLaborActivity",
    "BidTakeoffTotals",
    "BidLaborCostCodeTotals",
    "BidTypicalGroupTotals",
    "AffectDPCTypGroupViews",
    "BidTypGroupViews",
    "Boost",
    "DPCCalcFilter",
    "BidDPCSubscribers",
    "BidNotes",
    "BidTransactionsHistory",
    "STSTransactionHistory",
    "BidConditionUser",
    "BidPlanRooms",
)
_PAGE_SCOPED = PAGE_DELETE_CHILD_TABLES
_BID_SCOPED_POST = (
    "BidHotLinks",
    "BidNamedViews",
    "BidSettings",
    "BidLaborCostCodes",
    "BidTimeCardStates",
    "BidEmployees",
    "BidConditions",
    "BidZones",
    "BidConditionFolders",
    "BidLayers",
    "BidAreas",
    "BidTypAreas",
    "BidPages",
    "BidPageFolders",
)


class BidOperationsMixin(AccessIdentityAllocationMixin):
    @staticmethod
    def _global_settings_read_table_sql() -> str:
        return "[Settings]"

    @staticmethod
    def _global_settings_write_table_sql() -> str:
        return "[Settings]"

    def delete_bids(self, db_path: str, bid_uids: List[str]) -> bool:
        if not bid_uids:
            return True
        try:
            uids = [int(u) for u in bid_uids]
        except (TypeError, ValueError) as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.warning("Invalid bid uids passed to delete_bids: %s", bid_uids)
            return False
        placeholders_sql = placeholders(uids)
        page_subquery = (
            f"(SELECT UID FROM [BidPages] WHERE BidUID IN ({placeholders_sql}))"
        )
        bid_filter = f"BidUID IN ({placeholders_sql})"
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "Bids", ("UID",))
                cursor = conn.cursor()
                require_unique_bid_owned_uid_matches(cursor, "Bids", uids)

                def _del_bid(table: str) -> None:
                    if schema.optional_table_missing(table) or not schema.column_exists(
                        table, "BidUID"
                    ):
                        return
                    cursor.execute(f"DELETE FROM [{table}] WHERE {bid_filter}", *uids)

                def _del_page(table: str) -> None:
                    if (
                        schema.optional_table_missing(table)
                        or schema.optional_table_missing("BidPages")
                        or not schema.column_exists(table, "BidPageUID")
                        or not schema.column_exists("BidPages", "UID")
                        or not schema.column_exists("BidPages", "BidUID")
                    ):
                        return
                    cursor.execute(
                        f"DELETE FROM [{table}] WHERE BidPageUID IN {page_subquery}",
                        *uids,
                    )

                def _del_takeoff_link(table: str) -> None:
                    if (
                        schema.optional_table_missing(table)
                        or schema.optional_table_missing("BidTakeoffs")
                        or not schema.column_exists("BidTakeoffs", "UID")
                        or not schema.column_exists("BidTakeoffs", "BidUID")
                    ):
                        return
                    for reference_column in TAKEOFF_ANNOTATION_REFERENCE_COLUMNS:
                        if not schema.column_exists(table, reference_column):
                            continue
                        cursor.execute(
                            f"DELETE FROM [{table}] WHERE [{reference_column}] IN "
                            f"(SELECT [UID] FROM [BidTakeoffs] "
                            f"WHERE BidUID IN ({placeholders_sql}))",
                            *uids,
                        )

                def _del_child_by_bid_parent(
                    child_table: str, child_fk: str, parent_table: str
                ) -> None:
                    if (
                        schema.optional_table_missing(child_table)
                        or schema.optional_table_missing(parent_table)
                        or not schema.column_exists(child_table, child_fk)
                        or not schema.column_exists(parent_table, "UID")
                        or not schema.column_exists(parent_table, "BidUID")
                    ):
                        return
                    cursor.execute(
                        f"DELETE FROM [{child_table}] WHERE [{child_fk}] IN "
                        f"(SELECT [UID] FROM [{parent_table}] "
                        f"WHERE BidUID IN ({placeholders_sql}))",
                        *uids,
                    )

                if (
                    not schema.optional_table_missing("BidPercents")
                    and not schema.optional_table_missing("BidTakeoffs")
                    and schema.column_exists("BidPercents", "BidTakeoffUID")
                    and schema.column_exists("BidTakeoffs", "UID")
                    and schema.column_exists("BidTakeoffs", "BidUID")
                ):
                    cursor.execute(
                        "DELETE FROM [BidPercents] WHERE [BidTakeoffUID] IN "
                        f"(SELECT [UID] FROM [BidTakeoffs] WHERE BidUID IN ({placeholders_sql}))",
                        *uids,
                    )
                if (
                    not schema.optional_table_missing("BidSettings")
                    and not schema.optional_table_missing("BidPages")
                    and schema.column_exists("BidSettings", "BidPageSelectedUID")
                    and schema.column_exists("BidPages", "UID")
                    and schema.column_exists("BidPages", "BidUID")
                ):
                    cursor.execute(
                        "UPDATE [BidSettings] SET [BidPageSelectedUID]=NULL "
                        f"WHERE [BidPageSelectedUID] IN {page_subquery}",
                        *uids,
                    )
                for table in TAKEOFF_REFERENCE_TABLES:
                    _del_takeoff_link(table)
                for table in _PAGE_SCOPED:
                    _del_page(table)
                    _del_bid(table)
                for table in _BID_SCOPED_PRE:
                    _del_bid(table)
                for parent_table, child_fk in (
                    ("BidLaborCostCodes", "BidLaborCostCodeUID"),
                    ("BidTimeCardStates", "BidTimeCardStateUID"),
                ):
                    _del_child_by_bid_parent("BidPercents", child_fk, parent_table)
                for parent_table, child_fk in (
                    ("BidEmployees", "BidEmployeeUID"),
                    ("BidAreas", "BidAreaUID"),
                    ("BidTypAreas", "BidTypicalAreaUID"),
                    ("BidLaborCostCodes", "BidLaborCostCodeUID"),
                    ("BidTimeCardStates", "BidTimeCardStateUID"),
                ):
                    _del_child_by_bid_parent("BidTimeCards", child_fk, parent_table)
                for parent_table, child_fk in (
                    ("BidAreas", "BidAreaUID"),
                    ("BidTypAreas", "BidTypAreaUID"),
                ):
                    _del_child_by_bid_parent("BidTypAreaCounts", child_fk, parent_table)
                    _del_child_by_bid_parent("BidPageSettings", child_fk, parent_table)
                if (
                    not schema.optional_table_missing("ConditionSetStyles")
                    and not schema.optional_table_missing("BidConditions")
                    and schema.column_exists("ConditionSetStyles", "ConditionStyleUID")
                    and schema.column_exists("BidConditions", "UID")
                    and schema.column_exists("BidConditions", "BidUID")
                ):
                    cursor.execute(
                        "DELETE FROM [ConditionSetStyles] WHERE [ConditionStyleUID] IN "
                        f"(SELECT [UID] FROM [BidConditions] WHERE BidUID IN ({placeholders_sql}))",
                        *uids,
                    )
                if not schema.optional_table_missing("BidTakeoffs"):
                    if schema.column_exists("BidTakeoffs", "BidUID"):
                        cursor.execute(
                            "DELETE FROM [BidTakeoffs] "
                            f"WHERE BidUID IN ({placeholders_sql})",
                            *uids,
                        )
                    else:
                        _del_page("BidTakeoffs")
                for table in _BID_SCOPED_POST:
                    _del_bid(table)
                cursor.execute(
                    f"DELETE FROM [Bids] WHERE UID IN ({placeholders_sql})", *uids
                )
                return True
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception("Failed to delete bids %s from %s", bid_uids, db_path)
            return False

    def duplicate_bid(self, db_path: str, bid_uid: str) -> Optional[str]:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "Bids", ("UID",))
                cursor = conn.cursor()
                require_unique_bid_owned_uid_matches(cursor, "Bids", (bid_uid,))
                bid_cols = sorted(schema.get_columns("Bids"))
                cursor.execute(
                    f"SELECT {', '.join(f'[{c}]' for c in bid_cols)} "
                    "FROM [Bids] WHERE UID = ?",
                    bid_uid,
                )
                cols = [d[0] for d in cursor.description]
                source_row = cursor.fetchone()
                if not source_row:
                    return None
                bid_data = dict(zip(cols, source_row))
                for column, table in (
                    ("JobStatusUID", "JobStatuses"),
                    ("EstimatorUID", "Employees"),
                    ("PrManagerUID", "Employees"),
                    ("JobSiteManagerUID", "Employees"),
                ):
                    if column in bid_data:
                        require_optional_existing_unique_master_data_uid(
                            cursor, table, bid_data[column]
                        )
                if not schema.optional_table_missing("BidSettings"):
                    schema.require_column("BidSettings", "BidUID")
                    fetch_optional_bid_settings_row(cursor, bid_uid, ("BidUID",))
                self._require_duplicable_bid_relationships(cursor, schema, int(bid_uid))
                require_writable_bid_number_allocator(schema)
                settings_row = fetch_optional_global_settings_row(
                    cursor,
                    "[NextBidNo]",
                    table_sql=self._global_settings_read_table_sql(),
                )
                next_bid_no = normalize_next_bid_number(
                    settings_row[0] if settings_row is not None else None
                )
                now = datetime.datetime.now()
                new_guid = "{" + str(uuid.uuid4()).upper() + "}"
                new_bid_uid_int = self._next_uid_preserving_references(
                    cursor, schema, "Bids"
                )
                insert_cols = list(cols)
                overrides = {
                    "UID": new_bid_uid_int,
                    "BidNo": next_bid_no,
                    "GUID": new_guid,
                    "CopyFromBidNO": bid_data.get("BidNo"),
                    "CopyTimeStamp": now,
                    "CreateDateTime": now,
                    "ModDateTime": now,
                }
                self._execute_insert_values(
                    cursor,
                    schema,
                    "Bids",
                    {c: overrides.get(c, bid_data[c]) for c in insert_cols},
                    ("UID",),
                    "duplicate_bid",
                )
                new_bid_uid = str(new_bid_uid_int)
                duplicated_uid_maps: Dict[str, Dict[str, str]] = {}
                _uid_map_tables = {
                    "BidConditions",
                    "BidConditionFolders",
                    "BidLayers",
                    "BidAreas",
                    "BidPageFolders",
                    "BidNamedViews",
                }
                bid_tables = (
                    [
                        t
                        for t in BID_SECTIONS
                        if t not in HANDLED_SEPARATELY and t != "BidTypAreaCounts"
                    ]
                    + list(HANDLED_SEPARATELY - _uid_map_tables)
                    + [t for t in BID_TAIL_SECTIONS if t not in HANDLED_SEPARATELY]
                    + list(LEGACY_BID_TABLES_COPIED_BY_DUPLICATION)
                )
                for table in bid_tables:
                    duplicated_uid_maps.setdefault(table, {}).update(
                        self._copy_bid_table_rows(
                            cursor, table, "BidUID", bid_uid, new_bid_uid
                        )
                        or {}
                    )
                cond_folder_uid_map = self._copy_with_uid_map(
                    cursor, "BidConditionFolders", "BidUID", bid_uid, new_bid_uid
                )
                duplicated_uid_maps["BidConditionFolders"] = cond_folder_uid_map
                cond_uid_map = self._copy_with_uid_map(
                    cursor, "BidConditions", "BidUID", bid_uid, new_bid_uid
                )
                duplicated_uid_maps["BidConditions"] = cond_uid_map
                layer_uid_map = self._copy_with_uid_map(
                    cursor, "BidLayers", "BidUID", bid_uid, new_bid_uid
                )
                duplicated_uid_maps["BidLayers"] = layer_uid_map
                area_uid_map = self._copy_with_uid_map(
                    cursor, "BidAreas", "BidUID", bid_uid, new_bid_uid
                )
                duplicated_uid_maps["BidAreas"] = area_uid_map
                for old_area_uid, new_area_uid in area_uid_map.items():
                    duplicated_uid_maps.setdefault("BidTypAreaCounts", {}).update(
                        self._copy_bid_table_rows(
                            cursor,
                            "BidTypAreaCounts",
                            "BidAreaUID",
                            old_area_uid,
                            new_area_uid,
                        )
                        or {}
                    )
                page_folder_uid_map = self._copy_with_uid_map(
                    cursor, "BidPageFolders", "BidUID", bid_uid, new_bid_uid
                )
                duplicated_uid_maps["BidPageFolders"] = page_folder_uid_map
                named_view_uid_map = self._copy_with_uid_map(
                    cursor, "BidNamedViews", "BidUID", bid_uid, new_bid_uid
                )
                duplicated_uid_maps["BidNamedViews"] = named_view_uid_map
                page_cols = sorted(schema.get_columns("BidPages"))
                cursor.execute(
                    f"SELECT {', '.join(f'[{c}]' for c in page_cols)} "
                    "FROM [BidPages] WHERE BidUID = ?",
                    bid_uid,
                )
                page_rows = cursor.fetchall()
                require_valid_unique_bid_owned_uids(
                    (page_row[page_cols.index("UID")] for page_row in page_rows),
                    "BidPages",
                )
                page_uid_map = {}
                insert_page_cols = list(page_cols)
                for page_row in page_rows:
                    page_data = dict(zip(page_cols, page_row))
                    old_page_uid = str(int(page_data["UID"]))
                    new_page_uid_int = self._next_uid_preserving_references(
                        cursor, schema, "BidPages"
                    )
                    if "GUID" in page_data:
                        page_data["GUID"] = "{" + str(uuid.uuid4()).upper() + "}"
                    page_values = [
                        (
                            new_page_uid_int
                            if c == "UID"
                            else new_bid_uid if c == "BidUID" else page_data[c]
                        )
                        for c in insert_page_cols
                    ]
                    self._execute_insert_values(
                        cursor,
                        schema,
                        "BidPages",
                        dict(zip(insert_page_cols, page_values)),
                        ("UID", "BidUID"),
                        "duplicate_bid_page",
                    )
                    new_page_uid = str(new_page_uid_int)
                    page_uid_map[old_page_uid] = new_page_uid
                duplicated_uid_maps["BidPages"] = page_uid_map
                for table in PAGE_SECTIONS:
                    for old_page_uid, new_page_uid in page_uid_map.items():
                        duplicated_uid_maps.setdefault(table, {}).update(
                            self._copy_bid_table_rows(
                                cursor,
                                table,
                                "BidPageUID",
                                old_page_uid,
                                new_page_uid,
                                extra_overrides={"BidUID": new_bid_uid},
                            )
                            or {}
                        )
                self._remap_duplicated_relationships(
                    cursor, schema, duplicated_uid_maps, new_bid_uid
                )
                self._remap_duplicated_cover_sheet_selection(
                    cursor,
                    schema,
                    bid_data,
                    page_uid_map,
                    new_bid_uid,
                )
                persist_next_bid_number(
                    cursor,
                    settings_row,
                    next_bid_no + 1,
                    table_sql=self._global_settings_write_table_sql(),
                )
                return new_bid_uid
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception("Failed to duplicate bid %s in %s", bid_uid, db_path)
            return None

    def create_bid(
        self, db_path: str, project_uid: Optional[str], updates: Dict[str, object]
    ) -> Optional[str]:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "Bids", ("UID", "JobName"))
                require_writable_bid_number_allocator(schema)
                cursor = conn.cursor()
                if project_uid:
                    require_existing_unique_bid_owned_uid_matches(
                        cursor, "BidProjects", (project_uid,)
                    )
                new_folders = self._require_valid_new_bid_folder_references(updates)
                if new_folders and schema.optional_table_missing("BidPageFolders"):
                    raise RuntimeError(
                        "This OST database does not support page-folder persistence."
                    )
                if (
                    new_folders
                    and not schema.column_exists("BidPageFolders", "ParentUID")
                    and any(
                        folder.get("parent_uid") not in (None, "", 0, "0")
                        for folder in new_folders
                    )
                ):
                    raise RuntimeError(
                        "This OST database does not support page-folder hierarchy "
                        "persistence."
                    )
                job_status_uid = updates.get("job_status_uid")
                if schema.column_exists("Bids", "JobStatusUID"):
                    job_status_uid = require_optional_existing_unique_master_data_uid(
                        cursor, "JobStatuses", job_status_uid
                    )
                estimator_uid = updates.get("estimator_uid")
                if schema.column_exists("Bids", "EstimatorUID"):
                    estimator_uid = require_optional_existing_unique_master_data_uid(
                        cursor, "Employees", estimator_uid
                    )
                settings_row = None
                settings_select = ", ".join(
                    [
                        schema.optional_column("Settings", "NextBidNo", "1"),
                        schema.optional_column("Settings", "ScaleStyle", "1"),
                        schema.optional_column("Settings", "ScaleFactor1", "0.125"),
                        schema.optional_column("Settings", "ScaleFactor2", "12"),
                        schema.optional_column("Settings", "PageWidth", "42"),
                        schema.optional_column("Settings", "PageHeight", "30"),
                        schema.optional_column("Settings", "MeasureBase", "0"),
                        schema.optional_column("Settings", "TakeoffIncrements", "1"),
                    ]
                )
                settings_row = fetch_optional_global_settings_row(
                    cursor,
                    settings_select,
                    table_sql=self._global_settings_read_table_sql(),
                )
                if settings_row:
                    next_bid_no = normalize_next_bid_number(settings_row.NextBidNo)
                    def_scale_style = settings_row.ScaleStyle or 1
                    def_sf1 = settings_row.ScaleFactor1 or 0.125
                    def_sf2 = settings_row.ScaleFactor2 or 12.0
                    def_pw = settings_row.PageWidth or 42.0
                    def_ph = settings_row.PageHeight or 30.0
                    def_mb = settings_row.MeasureBase or 0
                    def_ti = settings_row.TakeoffIncrements or 1.0
                else:
                    next_bid_no = 1
                    def_scale_style, def_sf1, def_sf2 = 1, 0.125, 12.0
                    def_pw, def_ph = 42.0, 30.0
                    def_mb, def_ti = 0, 1.0
                new_bid_uid = self._next_uid_preserving_references(
                    cursor, schema, "Bids"
                )
                new_guid = "{" + str(uuid.uuid4()).upper() + "}"
                now = datetime.datetime.now().replace(second=0, microsecond=0)
                notes_raw = updates.get("notes", "") or ""
                notes_val = encode_text_blob(notes_raw)
                self._execute_insert_values(
                    cursor,
                    schema,
                    "Bids",
                    {
                        "UID": new_bid_uid,
                        "BidProjectUID": int(project_uid) if project_uid else None,
                        "GUID": new_guid,
                        "BidNo": next_bid_no,
                        "JobName": updates.get("job_name", "") or "",
                        "JobStatusUID": job_status_uid,
                        "EstimatorUID": estimator_uid,
                        "Notes": notes_val,
                        "BidDate": updates.get("bid_date"),
                        "JobID": updates.get("job_id", "") or "",
                        "CreateDateTime": now,
                        "MeasureBase": updates.get("measure_base", def_mb),
                        "TakeoffIncrements": updates.get("takeoff_increments", def_ti),
                        "ScaleStyle": updates.get("scale_style", def_scale_style),
                        "ScaleFactor1": updates.get("scale_factor1", def_sf1),
                        "ScaleFactor2": updates.get("scale_factor2", def_sf2),
                        "PageWidth": updates.get("page_width", def_pw),
                        "PageHeight": updates.get("page_height", def_ph),
                        "HoursPerDay": 8,
                        "LegendFlags": 41,
                        "BidType": 0,
                        "PriceUsing": 0,
                        "WeekStartDay": 0,
                        "PageScale": 0.0,
                        "CoverSheetSelItemType": 1,
                    },
                    ("UID", "JobName"),
                    "create_bid",
                )
                template_rows = []
                if not schema.optional_table_missing(
                    "BidLayers"
                ) and schema.column_exists("BidLayers", "IsTemplate"):
                    layer_select = ", ".join(
                        [
                            schema.optional_column("BidLayers", "UID", "NULL"),
                            schema.optional_column("BidLayers", "Name", "NULL"),
                            schema.optional_column("BidLayers", "Show", "-1"),
                            schema.optional_column("BidLayers", "IsLocked", "0"),
                            schema.optional_column("BidLayers", "Sequence", "0"),
                        ]
                    )
                    cursor.execute(
                        f"SELECT {layer_select} FROM [BidLayers] WHERE [IsTemplate] <> 0"
                    )
                    template_rows = cursor.fetchall()
                for i, tpl in enumerate(template_rows):
                    show_val = -1 if tpl.Show in (True, -1, 1) else 0
                    locked_val = -1 if tpl.IsLocked in (True, -1, 1) else 0
                    self._execute_insert_values(
                        cursor,
                        schema,
                        "BidLayers",
                        {
                            "UID": self._next_uid_preserving_references(
                                cursor, schema, "BidLayers"
                            ),
                            "BidUID": new_bid_uid,
                            "Name": tpl.Name,
                            "Show": show_val,
                            "IsLocked": locked_val,
                            "Sequence": tpl.Sequence if tpl.Sequence is not None else i,
                            "IsTemplate": 0,
                        },
                        ("UID", "BidUID", "Name"),
                        "create_bid_layer",
                    )
                pages = updates.get("pages", [])
                first_page_uid = None
                local_folder_uid_map: Dict[str, int] = {}
                if new_folders:
                    for nf in new_folders:
                        assigned_uid = self._next_uid_preserving_references(
                            cursor, schema, "BidPageFolders"
                        )
                        raw_parent = nf.get("parent_uid")
                        if raw_parent and str(raw_parent) in local_folder_uid_map:
                            parent_val = local_folder_uid_map[str(raw_parent)]
                        elif raw_parent:
                            try:
                                parent_val = int(raw_parent)
                            except (ValueError, TypeError):
                                parent_val = None
                        else:
                            parent_val = None
                        self._execute_insert_values(
                            cursor,
                            schema,
                            "BidPageFolders",
                            {
                                "UID": assigned_uid,
                                "BidUID": new_bid_uid,
                                "Name": nf.get("name") or "New Folder",
                                "ParentUID": parent_val,
                            },
                            ("UID", "BidUID", "Name"),
                            "create_bid_page_folder",
                        )
                        local_uid = nf.get("local_uid")
                        if local_uid:
                            local_folder_uid_map[str(local_uid)] = assigned_uid
                page_counter = 0
                for page in pages:
                    if page.get("width") is None:
                        continue
                    page_uid = self._next_uid_preserving_references(
                        cursor, schema, "BidPages"
                    )
                    if first_page_uid is None:
                        first_page_uid = page_uid
                    page_guid = "{" + str(uuid.uuid4()).upper() + "}"
                    raw_folder = page.get("folder_uid")
                    if raw_folder and str(raw_folder) in local_folder_uid_map:
                        folder_uid_val = local_folder_uid_map[str(raw_folder)]
                    elif raw_folder:
                        try:
                            folder_uid_val = int(raw_folder)
                        except (ValueError, TypeError):
                            folder_uid_val = None
                    else:
                        folder_uid_val = None
                    self._execute_insert_values(
                        cursor,
                        schema,
                        "BidPages",
                        {
                            "UID": page_uid,
                            "BidUID": new_bid_uid,
                            "SheetNo": page.get("sheet_no") or "",
                            "Name": page.get("name") or "",
                            "Width": page["width"],
                            "Height": page["height"],
                            "ScaleFactor1": page.get("scale_factor1", def_sf1),
                            "ScaleFactor2": page.get("scale_factor2", def_sf2),
                            "Show": page.get("show_mode", 0),
                            "RasterDrawMethod": 1,
                            "ScaleStyle": updates.get("scale_style", def_scale_style),
                            "GUID": page_guid,
                            "Index1": page.get("index") or 1,
                            "Sequence": page.get("sequence") or (page_counter + 1),
                            "MultiPageCount": page.get("multi_page_count") or 0,
                            "ImagePath": page.get("image_path") or "",
                            "OverlayImagePath": page.get("overlay_path") or "",
                            "BidPageFolderUID": folder_uid_val,
                        },
                        ("UID", "BidUID"),
                        "create_bid_page",
                    )
                    if not schema.optional_table_missing("BidLegends"):
                        self._execute_insert_values(
                            cursor,
                            schema,
                            "BidLegends",
                            {
                                "UID": self._next_uid_preserving_references(
                                    cursor, schema, "BidLegends"
                                ),
                                "BidUID": new_bid_uid,
                                "BidPageUID": page_uid,
                                "FontName": "Arial",
                                "FontSize": 10,
                                "MoveToCorner": -1,
                            },
                            ("UID", "BidUID", "BidPageUID"),
                            "create_bid_legend",
                        )
                    page_counter += 1
                if not schema.optional_table_missing("BidSettings"):
                    self._execute_insert_values(
                        cursor,
                        schema,
                        "BidSettings",
                        {
                            "UID": new_bid_uid,
                            "BidUID": new_bid_uid,
                            "BidPageSelectedUID": first_page_uid,
                        },
                        ("BidUID",),
                        "create_bid_settings",
                    )
                if first_page_uid is not None:
                    self._execute_update_values(
                        cursor,
                        schema,
                        "Bids",
                        {"CoverSheetSelItemUID": first_page_uid},
                        ("UID",),
                        "[UID] = ?",
                        [new_bid_uid],
                        "create_bid_cover_sheet_selection",
                        allow_empty=True,
                    )
                persist_next_bid_number(
                    cursor,
                    settings_row,
                    next_bid_no + 1,
                    table_sql=self._global_settings_write_table_sql(),
                )
                return str(new_bid_uid)
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception(
                "Failed to create bid in %s for project %s", db_path, project_uid
            )
            return None

    @staticmethod
    def _require_valid_new_bid_folder_references(
        updates: Dict[str, object],
    ) -> list[dict]:
        normalized_folders: list[dict] = []
        folder_by_uid: dict[str, dict] = {}
        parent_by_uid: dict[str, str | None] = {}
        for index, source_folder in enumerate(updates.get("new_folders", [])):
            folder = dict(source_folder)
            local_uid = str(folder.get("local_uid") or f"__folder_{index}")
            if local_uid in folder_by_uid:
                raise ValueError(
                    f"New Bid contains duplicate page-folder identity {local_uid}."
                )
            folder["local_uid"] = local_uid
            normalized_folders.append(folder)
            folder_by_uid[local_uid] = folder
            parent_uid = folder.get("parent_uid")
            parent_by_uid[local_uid] = (
                None if parent_uid in (None, "", 0, "0") else str(parent_uid)
            )
        for local_uid, parent_uid in parent_by_uid.items():
            if parent_uid is not None and parent_uid not in folder_by_uid:
                raise DanglingBidOwnedReferenceError(
                    f"New Bid page folder {local_uid} references unavailable "
                    f"page folder {parent_uid}."
                )
        require_acyclic_bid_owned_parent_graph(parent_by_uid, "BidPageFolders")
        for page in updates.get("pages", []):
            folder_uid = page.get("folder_uid")
            if folder_uid in (None, "", 0, "0"):
                continue
            if str(folder_uid) not in folder_by_uid:
                raise DanglingBidOwnedReferenceError(
                    f"New Bid page references unavailable page folder {folder_uid}."
                )
        ordered_folders: list[dict] = []
        appended: set[str] = set()

        def append_with_parent(local_uid: str) -> None:
            if local_uid in appended:
                return
            parent_uid = parent_by_uid[local_uid]
            if parent_uid is not None:
                append_with_parent(parent_uid)
            ordered_folders.append(folder_by_uid[local_uid])
            appended.add(local_uid)

        for folder in normalized_folders:
            append_with_parent(str(folder["local_uid"]))
        return ordered_folders

    def _copy_bid_table_rows(
        self,
        cursor: pyodbc.Cursor,
        table: str,
        uid_col: str,
        old_uid: str,
        new_uid: str,
        extra_overrides: dict = None,
    ) -> Dict[str, str]:
        uid_map: Dict[str, str] = {}
        schema = self._schema(cursor.connection)
        try:
            if schema.optional_table_missing(table) or not schema.column_exists(
                table, uid_col
            ):
                return uid_map
            cols = sorted(schema.get_columns(table))
            cursor.execute(
                f"SELECT {', '.join(f'[{c}]' for c in cols)} "
                f"FROM [{table}] WHERE [{uid_col}] = ?",
                old_uid,
            )
            binary_cols = {d[0] for d in cursor.description if d[1] is bytearray}
            rows = [dict(zip(cols, row)) for row in cursor.fetchall()]
            if not rows:
                return uid_map
            if table == "BidPageSettings":
                rows = canonicalize_page_area_settings(rows)
            has_uid = "UID" in cols
            if has_uid:
                require_valid_unique_bid_owned_uids((row["UID"] for row in rows), table)
            insert_cols = cols
            for row_data in rows:
                row_data[uid_col] = new_uid
                if extra_overrides:
                    row_data.update(extra_overrides)
                if "GUID" in row_data:
                    row_data["GUID"] = "{" + str(uuid.uuid4()).upper() + "}"
                if has_uid:
                    old_row_uid = str(int(row_data["UID"]))
                    new_row_uid = self._next_uid_preserving_references(
                        cursor, schema, table
                    )
                    row_data["UID"] = new_row_uid
                values = []
                for c in insert_cols:
                    val = row_data[c]
                    if c in binary_cols and val is not None:
                        val = coerce_binary_column_value(val)
                    values.append(val)
                self._execute_insert_values(
                    cursor,
                    schema,
                    table,
                    dict(zip(insert_cols, values)),
                    (uid_col,),
                    f"copy_{table}",
                )
                if has_uid:
                    uid_map[old_row_uid] = str(new_row_uid)
        except pyodbc.Error as exc:
            if self._record_caught_mutation_error(exc):
                raise
        return uid_map

    def _remap_duplicated_relationships(
        self,
        cursor,
        schema,
        duplicated_uid_maps: Dict[str, Dict[str, str]],
        new_bid_uid: str,
    ) -> None:
        for relationship in BID_RELATIONSHIPS:
            parent_uid_map = duplicated_uid_maps.get(relationship.parent_table, {})
            child_uid_map = duplicated_uid_maps.get(relationship.child_table, {})
            if not parent_uid_map:
                continue
            if schema.column_exists(relationship.child_table, "BidUID"):
                where_columns = ("BidUID", relationship.child_column)
                scopes = ((new_bid_uid,),)
            elif schema.column_exists(relationship.child_table, "BidPageUID"):
                where_columns = ("BidPageUID", relationship.child_column)
                scopes = tuple(
                    (new_page_uid,)
                    for new_page_uid in duplicated_uid_maps.get("BidPages", {}).values()
                )
            else:
                if not child_uid_map:
                    continue
                where_columns = ("UID", relationship.child_column)
                scopes = tuple(
                    (new_child_uid,) for new_child_uid in child_uid_map.values()
                )
            for old_parent_uid, new_parent_uid in parent_uid_map.items():
                for scope in scopes:
                    self._update_if_columns(
                        cursor,
                        schema,
                        relationship.child_table,
                        relationship.child_column,
                        new_parent_uid,
                        where_columns,
                        (*scope, old_parent_uid),
                    )

    def _require_duplicable_bid_relationships(
        self,
        cursor,
        schema,
        bid_uid: int,
    ) -> None:
        checked: set[tuple[str, str, str, str]] = set()
        for relationship in BID_RELATIONSHIPS:
            key = (
                relationship.child_table,
                relationship.child_column,
                relationship.parent_table,
                relationship.parent_column,
            )
            if key in checked:
                continue
            checked.add(key)
            if schema.optional_table_missing(
                relationship.child_table
            ) or schema.optional_table_missing(relationship.parent_table):
                continue
            child_columns = schema.get_columns(relationship.child_table)
            parent_columns = schema.get_columns(relationship.parent_table)
            if not {
                "UID",
                "BidUID",
                relationship.child_column,
            }.issubset(child_columns) or not {
                "BidUID",
                relationship.parent_column,
            }.issubset(
                parent_columns
            ):
                continue
            cursor.execute(
                f"SELECT [child].[UID], [child].[{relationship.child_column}] "
                f"FROM [{relationship.child_table}] AS [child] "
                "WHERE [child].[BidUID] = ? AND "
                f"[child].[{relationship.child_column}] IS NOT NULL AND "
                f"[child].[{relationship.child_column}] <> 0",
                bid_uid,
            )
            child_rows = cursor.fetchall()
            if not child_rows:
                continue
            cursor.execute(
                f"SELECT [{relationship.parent_column}] "
                f"FROM [{relationship.parent_table}] WHERE [BidUID] = ?",
                bid_uid,
            )
            parent_uids = {int(row[0]) for row in cursor.fetchall()}
            missing_row = next(
                (row for row in child_rows if int(row[1]) not in parent_uids),
                None,
            )
            if missing_row is not None:
                raise DanglingBidOwnedReferenceError(
                    f"{relationship.child_table}.UID={int(missing_row[0])} "
                    f"references missing {relationship.parent_table}.UID="
                    f"{int(missing_row[1])} "
                    f"through {relationship.child_column}."
                )
        self._require_duplicable_indirect_area_counts(cursor, schema, bid_uid)
        self._require_duplicable_indirect_page_relationships(cursor, schema, bid_uid)
        for table in (
            "BidTakeoffs",
            "BidAreas",
            "BidConditionFolders",
            "BidPageFolders",
        ):
            if schema.optional_table_missing(table):
                continue
            columns = schema.get_columns(table)
            if not {"UID", "BidUID", "ParentUID"}.issubset(columns):
                continue
            cursor.execute(
                f"SELECT [UID], [ParentUID] FROM [{table}] WHERE [BidUID] = ?",
                bid_uid,
            )
            require_acyclic_bid_owned_parent_graph(
                {row[0]: row[1] for row in cursor.fetchall()},
                table,
            )

    @staticmethod
    def _require_duplicable_indirect_area_counts(cursor, schema, bid_uid: int) -> None:
        table = "BidTypAreaCounts"
        required_tables = (table, "BidAreas", "BidTypAreas")
        if any(schema.optional_table_missing(name) for name in required_tables):
            return
        if not {
            "UID",
            "BidAreaUID",
            "BidTypAreaUID",
        }.issubset(schema.get_columns(table)):
            return
        if not {"UID", "BidUID"}.issubset(schema.get_columns("BidAreas")) or not {
            "UID",
            "BidUID",
        }.issubset(schema.get_columns("BidTypAreas")):
            return
        cursor.execute("SELECT [UID] FROM [BidAreas] WHERE [BidUID]=?", bid_uid)
        area_uids = {int(row[0]) for row in cursor.fetchall()}
        if not area_uids:
            return
        cursor.execute("SELECT [UID] FROM [BidTypAreas] WHERE [BidUID]=?", bid_uid)
        typical_area_uids = {int(row[0]) for row in cursor.fetchall()}
        cursor.execute(
            "SELECT [UID], [BidAreaUID], [BidTypAreaUID] " "FROM [BidTypAreaCounts]"
        )
        rows = [
            row
            for row in cursor.fetchall()
            if row[1] not in (None, "", 0, "0") and int(row[1]) in area_uids
        ]
        require_valid_unique_bid_owned_uids((row[0] for row in rows), table)
        missing_row = next(
            (
                row
                for row in rows
                if row[2] not in (None, "", 0, "0")
                and int(row[2]) not in typical_area_uids
            ),
            None,
        )
        if missing_row is not None:
            raise DanglingBidOwnedReferenceError(
                f"BidTypAreaCounts.UID={int(missing_row[0])} references missing "
                f"BidTypAreas.UID={int(missing_row[2])} through BidTypAreaUID."
            )

    @staticmethod
    def _require_duplicable_indirect_page_relationships(
        cursor,
        schema,
        bid_uid: int,
    ) -> None:
        if schema.optional_table_missing("BidPages") or not {
            "UID",
            "BidUID",
        }.issubset(schema.get_columns("BidPages")):
            return
        cursor.execute("SELECT [UID] FROM [BidPages] WHERE [BidUID]=?", bid_uid)
        page_uids = [int(row[0]) for row in cursor.fetchall()]
        if not page_uids:
            return
        checked: set[tuple[str, str, str, str]] = set()
        for relationship in BID_RELATIONSHIPS:
            if relationship.child_table not in PAGE_SECTIONS:
                continue
            key = (
                relationship.child_table,
                relationship.child_column,
                relationship.parent_table,
                relationship.parent_column,
            )
            if key in checked:
                continue
            checked.add(key)
            if schema.optional_table_missing(
                relationship.child_table
            ) or schema.optional_table_missing(relationship.parent_table):
                continue
            child_columns = schema.get_columns(relationship.child_table)
            parent_columns = schema.get_columns(relationship.parent_table)
            if (
                "BidUID" in child_columns
                or not {
                    "BidPageUID",
                    relationship.child_column,
                }.issubset(child_columns)
                or not {
                    "BidUID",
                    relationship.parent_column,
                }.issubset(parent_columns)
            ):
                continue
            child_uid_sql = "[UID]" if "UID" in child_columns else "NULL AS [UID]"
            child_rows = []
            for page_uid in page_uids:
                cursor.execute(
                    f"SELECT {child_uid_sql}, [{relationship.child_column}] "
                    f"FROM [{relationship.child_table}] WHERE [BidPageUID]=? "
                    f"AND [{relationship.child_column}] IS NOT NULL "
                    f"AND [{relationship.child_column}] <> 0",
                    page_uid,
                )
                child_rows.extend(cursor.fetchall())
            if not child_rows:
                continue
            cursor.execute(
                f"SELECT [{relationship.parent_column}] "
                f"FROM [{relationship.parent_table}] WHERE [BidUID]=?",
                bid_uid,
            )
            parent_uids = {int(row[0]) for row in cursor.fetchall()}
            missing_row = next(
                (row for row in child_rows if int(row[1]) not in parent_uids),
                None,
            )
            if missing_row is not None:
                child_uid = (
                    str(int(missing_row[0]))
                    if missing_row[0] is not None
                    else "<legacy>"
                )
                raise DanglingBidOwnedReferenceError(
                    f"{relationship.child_table}.UID={child_uid} references missing "
                    f"{relationship.parent_table}.UID={int(missing_row[1])} "
                    f"through {relationship.child_column}."
                )

    def _remap_duplicated_cover_sheet_selection(
        self,
        cursor,
        schema,
        source_bid: Dict[str, object],
        page_uid_map: Dict[str, str],
        new_bid_uid: str,
    ) -> None:
        try:
            selection_type = int(source_bid.get("CoverSheetSelItemType") or 0)
        except (TypeError, ValueError):
            return
        if selection_type != COVER_SHEET_PAGE_SELECTION_TYPE:
            return
        try:
            selected_uid = str(int(source_bid.get("CoverSheetSelItemUID") or 0))
        except (TypeError, ValueError):
            new_selected_uid = None
        else:
            new_selected_uid = page_uid_map.get(selected_uid)
        self._update_if_columns(
            cursor,
            schema,
            "Bids",
            "CoverSheetSelItemUID",
            new_selected_uid,
            ("UID",),
            (new_bid_uid,),
        )

    def _copy_with_uid_map(
        self,
        cursor: pyodbc.Cursor,
        table: str,
        uid_col: str,
        old_uid: str,
        new_uid: str,
    ) -> dict:
        uid_map = {}
        schema = self._schema(cursor.connection)
        try:
            if schema.optional_table_missing(table) or not schema.column_exists(
                table, uid_col
            ):
                return uid_map
            cols = sorted(schema.get_columns(table))
            cursor.execute(
                f"SELECT {', '.join(f'[{c}]' for c in cols)} "
                f"FROM [{table}] WHERE [{uid_col}] = ?",
                old_uid,
            )
            binary_cols = {d[0] for d in cursor.description if d[1] is bytearray}
            rows = cursor.fetchall()
            if not rows:
                return uid_map
            require_valid_unique_bid_owned_uids(
                (row[cols.index("UID")] for row in rows),
                table,
            )
            insert_cols = cols
            for row in rows:
                row_data = dict(zip(cols, row))
                old_row_uid = str(int(row_data["UID"]))
                new_row_uid_int = self._next_uid_preserving_references(
                    cursor, schema, table
                )
                row_data["UID"] = new_row_uid_int
                row_data[uid_col] = new_uid
                if "GUID" in row_data:
                    row_data["GUID"] = "{" + str(uuid.uuid4()).upper() + "}"
                values = []
                for c in insert_cols:
                    val = row_data[c]
                    if c in binary_cols and val is not None:
                        val = coerce_binary_column_value(val)
                    values.append(val)
                self._execute_insert_values(
                    cursor,
                    schema,
                    table,
                    dict(zip(insert_cols, values)),
                    ("UID", uid_col),
                    f"copy_with_uid_map_{table}",
                )
                uid_map[old_row_uid] = str(new_row_uid_int)
        except pyodbc.Error as exc:
            if self._record_caught_mutation_error(exc):
                raise
        return uid_map

    def _update_if_columns(
        self,
        cursor,
        schema,
        table: str,
        set_column: str,
        set_value,
        where_columns: tuple[str, ...],
        where_values: tuple,
    ) -> None:
        if schema.optional_table_missing(table):
            return
        required = (set_column, *where_columns)
        missing = [
            column for column in required if not schema.column_exists(table, column)
        ]
        if missing:
            for column in missing:
                schema.log_optional_write_skip(
                    table, column, f"update_{table}_{set_column}"
                )
            return
        where_clause = " AND ".join(f"[{column}]=?" for column in where_columns)
        cursor.execute(
            f"UPDATE [{table}] SET [{set_column}]=? WHERE {where_clause}",
            set_value,
            *where_values,
        )
