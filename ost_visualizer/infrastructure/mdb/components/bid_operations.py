import datetime
import uuid
from typing import Dict, List, Optional
import pyodbc
from ..schema_contract import BID_SECTIONS, BID_TAIL_SECTIONS, PAGE_SECTIONS
from .constants import (
    HANDLED_SEPARATELY,
    PAGE_DELETE_CHILD_TABLES,
    TAKEOFF_REFERENCE_TABLES,
)
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
_PAGE_SCOPED = (
    "BidPercents",
    *PAGE_DELETE_CHILD_TABLES,
)
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


class BidOperationsMixin:
    def delete_bids(self, db_path: str, bid_uids: List[str]) -> bool:
        if not bid_uids:
            return True
        try:
            uids = [int(u) for u in bid_uids]
        except (TypeError, ValueError):
            self.logger.exception(
                "Invalid bid uids passed to delete_bids: %s", bid_uids
            )
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
                        or not schema.column_exists(table, "BidTakeoffFromUID")
                        or not schema.column_exists("BidTakeoffs", "UID")
                        or not schema.column_exists("BidTakeoffs", "BidUID")
                    ):
                        return
                    cursor.execute(
                        f"DELETE FROM [{table}] WHERE [BidTakeoffFromUID] IN "
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
        except Exception:
            self.logger.exception("Failed to delete bids %s from %s", bid_uids, db_path)
            return False

    def duplicate_bid(self, db_path: str, bid_uid: str) -> Optional[str]:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "Bids", ("UID",))
                cursor = conn.cursor()
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
                next_bid_no = 1
                if not schema.optional_table_missing(
                    "Settings"
                ) and schema.column_exists("Settings", "NextBidNo"):
                    cursor.execute("SELECT [NextBidNo] FROM [Settings]")
                    settings_row = cursor.fetchone()
                    next_bid_no = (
                        int(settings_row[0])
                        if (settings_row and settings_row[0] is not None)
                        else 1
                    )
                now = datetime.datetime.now()
                new_guid = "{" + str(uuid.uuid4()).upper() + "}"
                new_bid_uid = str(self._next_uid(cursor, "Bids"))
                insert_cols = list(cols)
                overrides = {
                    "UID": int(new_bid_uid),
                    "BidNo": next_bid_no,
                    "GUID": new_guid,
                    "CopyFromBidNO": bid_data.get("BidNo"),
                    "CopyTimeStamp": now,
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
                _uid_map_tables = {
                    "BidConditions",
                    "BidConditionFolders",
                    "BidLayers",
                    "BidAreas",
                    "BidPageFolders",
                    "BidNamedViews",
                }
                bid_tables = (
                    [t for t in BID_SECTIONS if t not in HANDLED_SEPARATELY]
                    + list(HANDLED_SEPARATELY - _uid_map_tables)
                    + [t for t in BID_TAIL_SECTIONS if t not in HANDLED_SEPARATELY]
                    + [
                        "AffectDPCTypGroupViews",
                        "BidLaborCostCodeTotals",
                        "BidTypicalGroupTotals",
                        "Boost",
                        "DPCCalcFilter",
                        "BidLaborActivity",
                        "BidLaborCostCodes",
                        "BidDPCSubscribers",
                        "BidEmployees",
                        "BidNotes",
                        "BidTimeCardStates",
                    ]
                )
                for table in bid_tables:
                    self._copy_bid_table_rows(
                        cursor, table, "BidUID", bid_uid, new_bid_uid
                    )
                cond_folder_uid_map = self._copy_with_uid_map(
                    cursor, "BidConditionFolders", "BidUID", bid_uid, new_bid_uid
                )
                cond_uid_map = self._copy_with_uid_map(
                    cursor, "BidConditions", "BidUID", bid_uid, new_bid_uid
                )
                layer_uid_map = self._copy_with_uid_map(
                    cursor, "BidLayers", "BidUID", bid_uid, new_bid_uid
                )
                area_uid_map = self._copy_with_uid_map(
                    cursor, "BidAreas", "BidUID", bid_uid, new_bid_uid
                )
                page_folder_uid_map = self._copy_with_uid_map(
                    cursor, "BidPageFolders", "BidUID", bid_uid, new_bid_uid
                )
                named_view_uid_map = self._copy_with_uid_map(
                    cursor, "BidNamedViews", "BidUID", bid_uid, new_bid_uid
                )
                page_cols = sorted(schema.get_columns("BidPages"))
                cursor.execute(
                    f"SELECT {', '.join(f'[{c}]' for c in page_cols)} "
                    "FROM [BidPages] WHERE BidUID = ?",
                    bid_uid,
                )
                page_rows = cursor.fetchall()
                page_uid_map = {}
                insert_page_cols = list(page_cols)
                for page_row in page_rows:
                    page_data = dict(zip(page_cols, page_row))
                    old_page_uid = str(int(page_data["UID"]))
                    new_page_uid_int = self._next_uid(cursor, "BidPages")
                    new_page_uid = str(new_page_uid_int)
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
                    page_uid_map[old_page_uid] = new_page_uid
                for table in PAGE_SECTIONS:
                    for old_page_uid, new_page_uid in page_uid_map.items():
                        self._copy_bid_table_rows(
                            cursor,
                            table,
                            "BidPageUID",
                            old_page_uid,
                            new_page_uid,
                            extra_overrides={"BidUID": new_bid_uid},
                        )
                for old_page_uid, new_page_uid in page_uid_map.items():
                    self._update_if_columns(
                        cursor,
                        schema,
                        "BidHotLinks",
                        "BidPageUID",
                        new_page_uid,
                        ("BidUID", "BidPageUID"),
                        (new_bid_uid, old_page_uid),
                    )
                    self._update_if_columns(
                        cursor,
                        schema,
                        "BidNamedViews",
                        "BidPageUID",
                        new_page_uid,
                        ("BidUID", "BidPageUID"),
                        (new_bid_uid, old_page_uid),
                    )
                    self._update_if_columns(
                        cursor,
                        schema,
                        "BidSettings",
                        "BidPageSelectedUID",
                        new_page_uid,
                        ("BidUID", "BidPageSelectedUID"),
                        (new_bid_uid, old_page_uid),
                    )
                for old_area_uid, new_area_uid in area_uid_map.items():
                    if (
                        not schema.optional_table_missing("BidPageSettings")
                        and not schema.optional_table_missing("BidPages")
                        and schema.column_exists("BidPageSettings", "BidAreaUID")
                        and schema.column_exists("BidPageSettings", "BidPageUID")
                        and schema.column_exists("BidPages", "UID")
                        and schema.column_exists("BidPages", "BidUID")
                    ):
                        cursor.execute(
                            "UPDATE [BidPageSettings] SET [BidAreaUID]=? "
                            "WHERE [BidAreaUID]=? AND [BidPageUID] IN "
                            "(SELECT [UID] FROM [BidPages] WHERE [BidUID]=?)",
                            new_area_uid,
                            old_area_uid,
                            new_bid_uid,
                        )
                for old_cond_uid, new_cond_uid in cond_uid_map.items():
                    self._update_if_columns(
                        cursor,
                        schema,
                        "BidTakeoffs",
                        "BidConditionUID",
                        new_cond_uid,
                        ("BidUID", "BidConditionUID"),
                        (new_bid_uid, old_cond_uid),
                    )
                _layer_ref_tables = [
                    "BidConditions",
                    "BidZones",
                    "BidTakeoffs",
                    "BidHighlights",
                    "BidTexts",
                    "BidDimensions",
                    "BidArrows",
                    "BidALines",
                    "BidCallOuts",
                    "BidAnnotationRects",
                    "BidAnnotationOvals",
                    "BidAnnotationPolygons",
                    "BidAnnotationClouds",
                    "BidAnnoInk",
                    "BidLegends",
                    "BidHotLinks",
                    "BidNamedViews",
                ]
                for old_area_uid, new_area_uid in area_uid_map.items():
                    self._update_if_columns(
                        cursor,
                        schema,
                        "BidTakeoffs",
                        "BidAreaUID",
                        new_area_uid,
                        ("BidUID", "BidAreaUID"),
                        (new_bid_uid, old_area_uid),
                    )
                for old_cf_uid, new_cf_uid in cond_folder_uid_map.items():
                    self._update_if_columns(
                        cursor,
                        schema,
                        "BidConditions",
                        "BidConditionFolderUID",
                        new_cf_uid,
                        ("BidUID", "BidConditionFolderUID"),
                        (new_bid_uid, old_cf_uid),
                    )
                for old_pf_uid, new_pf_uid in page_folder_uid_map.items():
                    self._update_if_columns(
                        cursor,
                        schema,
                        "BidPages",
                        "BidPageFolderUID",
                        new_pf_uid,
                        ("BidUID", "BidPageFolderUID"),
                        (new_bid_uid, old_pf_uid),
                    )
                for old_nv_uid, new_nv_uid in named_view_uid_map.items():
                    self._update_if_columns(
                        cursor,
                        schema,
                        "BidHotLinks",
                        "BidPageViewUID",
                        new_nv_uid,
                        ("BidUID", "BidPageViewUID"),
                        (new_bid_uid, old_nv_uid),
                    )
                for old_layer_uid, new_layer_uid in layer_uid_map.items():
                    for tbl in _layer_ref_tables:
                        try:
                            self._update_if_columns(
                                cursor,
                                schema,
                                tbl,
                                "BidLayerUID",
                                new_layer_uid,
                                ("BidUID", "BidLayerUID"),
                                (new_bid_uid, old_layer_uid),
                            )
                        except pyodbc.Error:
                            pass
                if not schema.optional_table_missing(
                    "Settings"
                ) and schema.column_exists("Settings", "NextBidNo"):
                    cursor.execute(
                        "UPDATE [Settings] SET [NextBidNo] = ?", next_bid_no + 1
                    )
                return new_bid_uid
        except Exception:
            self.logger.exception("Failed to duplicate bid %s in %s", bid_uid, db_path)
            return None

    def create_bid(
        self, db_path: str, project_uid: Optional[str], updates: Dict[str, object]
    ) -> Optional[str]:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "Bids", ("UID", "JobName"))
                cursor = conn.cursor()
                settings_row = None
                if not schema.optional_table_missing("Settings"):
                    settings_select = ", ".join(
                        [
                            schema.optional_column("Settings", "NextBidNo", "1"),
                            schema.optional_column("Settings", "ScaleStyle", "1"),
                            schema.optional_column("Settings", "ScaleFactor1", "0.125"),
                            schema.optional_column("Settings", "ScaleFactor2", "12"),
                            schema.optional_column("Settings", "PageWidth", "42"),
                            schema.optional_column("Settings", "PageHeight", "30"),
                            schema.optional_column("Settings", "MeasureBase", "0"),
                            schema.optional_column(
                                "Settings", "TakeoffIncrements", "1"
                            ),
                        ]
                    )
                    cursor.execute(f"SELECT {settings_select} FROM [Settings]")
                    settings_row = cursor.fetchone()
                if settings_row:
                    next_bid_no = int(settings_row.NextBidNo or 1)
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
                new_bid_uid = self._next_uid(cursor, "Bids")
                new_guid = "{" + str(uuid.uuid4()).upper() + "}"
                now = datetime.datetime.now().replace(second=0, microsecond=0)
                notes_raw = updates.get("notes", "") or ""
                notes_val = (
                    notes_raw.encode("utf-8")
                    if isinstance(notes_raw, str)
                    else notes_raw
                )
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
                        "JobStatusUID": updates.get("job_status_uid"),
                        "EstimatorUID": updates.get("estimator_uid"),
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
                            "UID": self._next_uid(cursor, "BidLayers"),
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
                new_folders = updates.get("new_folders", [])
                if new_folders:
                    for nf in new_folders:
                        assigned_uid = self._next_uid(cursor, "BidPageFolders")
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
                    page_uid = self._next_uid(cursor, "BidPages")
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
                                "UID": self._next_uid(cursor, "BidLegends"),
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
                if not schema.optional_table_missing(
                    "Settings"
                ) and schema.column_exists("Settings", "NextBidNo"):
                    cursor.execute(
                        "UPDATE [Settings] SET [NextBidNo] = ?", next_bid_no + 1
                    )
                return str(new_bid_uid)
        except Exception:
            self.logger.exception(
                "Failed to create bid in %s for project %s", db_path, project_uid
            )
            return None

    def _copy_bid_table_rows(
        self,
        cursor: pyodbc.Cursor,
        table: str,
        uid_col: str,
        old_uid: str,
        new_uid: str,
        extra_overrides: dict = None,
    ) -> None:
        schema = self._schema(cursor.connection)
        try:
            if schema.optional_table_missing(table) or not schema.column_exists(
                table, uid_col
            ):
                return
            cols = sorted(schema.get_columns(table))
            cursor.execute(
                f"SELECT {', '.join(f'[{c}]' for c in cols)} "
                f"FROM [{table}] WHERE [{uid_col}] = ?",
                old_uid,
            )
            binary_cols = {d[0] for d in cursor.description if d[1] is bytearray}
            rows = cursor.fetchall()
            if not rows:
                return
            has_uid = "UID" in cols
            insert_cols = cols
            for row in rows:
                row_data = dict(zip(cols, row))
                row_data[uid_col] = new_uid
                if extra_overrides:
                    row_data.update(extra_overrides)
                if has_uid:
                    cursor.execute(f"SELECT MAX([UID]) FROM [{table}]")
                    max_uid_result = cursor.fetchone()[0]
                    row_data["UID"] = (
                        int(max_uid_result) + 1 if max_uid_result is not None else 1
                    )
                values = []
                for c in insert_cols:
                    val = row_data[c]
                    if c in binary_cols and val is not None and isinstance(val, str):
                        val = val.encode("utf-8")
                    values.append(val)
                self._execute_insert_values(
                    cursor,
                    schema,
                    table,
                    dict(zip(insert_cols, values)),
                    (uid_col,),
                    f"copy_{table}",
                )
        except pyodbc.Error:
            pass

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
            insert_cols = cols
            for row in rows:
                row_data = dict(zip(cols, row))
                old_row_uid = str(int(row_data["UID"]))
                new_row_uid_int = self._next_uid(cursor, table)
                row_data["UID"] = new_row_uid_int
                row_data[uid_col] = new_uid
                values = []
                for c in insert_cols:
                    val = row_data[c]
                    if c in binary_cols and val is not None and isinstance(val, str):
                        val = val.encode("utf-8")
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
        except pyodbc.Error:
            pass
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
