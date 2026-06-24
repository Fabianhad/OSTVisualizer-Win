import uuid
import pyodbc
from ....domain.entities.area import BidAreaChangeset
from ....domain.services.uom_service import normalize_uom_for_system
from ...parsers.position_parser import convert_elevation_in_name
from .constants import PAGE_DELETE_CHILD_TABLES, TAKEOFF_REFERENCE_TABLES
from .overlay_rect import default_overlay_rect


class SettingsOperationsMixin:
    @staticmethod
    def _windows_path_separators(path) -> str:
        if not path:
            return ""
        return str(path).replace("/", "\\")

    def save_cover_sheet(self, db_path: str, bid_uid: str, updates: dict) -> bool:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "Bids", ("UID",))
                cursor = conn.cursor()
                bid_uid_int = int(bid_uid)
                new_mb = int(updates.get("measure_base", 0))
                old_mb = new_mb
                if schema.column_exists("Bids", "MeasureBase"):
                    cursor.execute(
                        "SELECT [MeasureBase] FROM [Bids] WHERE [UID]=?", bid_uid_int
                    )
                    row = cursor.fetchone()
                    old_mb = int(row[0] or 0) if row else new_mb
                notes = updates.get("notes", "") or ""
                if isinstance(notes, str):
                    notes = notes.encode("utf-8")
                self._execute_update_values(
                    cursor,
                    schema,
                    "Bids",
                    {
                        "JobStatusUID": updates.get("job_status_uid"),
                        "JobName": updates.get("job_name", ""),
                        "EstimatorUID": updates.get("estimator_uid"),
                        "Notes": notes,
                        "BidDate": updates.get("bid_date"),
                        "BidNo": updates.get("bid_no"),
                        "JobID": updates.get("job_id", ""),
                        "MeasureBase": new_mb,
                        "TakeoffIncrements": updates.get("takeoff_increments", 1.0),
                        "ScaleStyle": updates.get("scale_style", 1),
                        "ScaleFactor1": updates.get("scale_factor1", 0.25),
                        "ScaleFactor2": updates.get("scale_factor2", 12.0),
                        "PageWidth": updates.get("page_width", 42.0),
                        "PageHeight": updates.get("page_height", 30.0),
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
                for folder in updates.get("folders", []):
                    if not folder.get("uid") or not folder.get("name"):
                        continue
                    parent_uid_val = (
                        int(folder["parent_uid"]) if folder.get("parent_uid") else None
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
                local_uid_map: dict = {}
                for new_folder in updates.get("new_folders", []):
                    name = new_folder.get("name") or "New Folder"
                    raw_parent = new_folder.get("parent_uid")
                    if raw_parent and str(raw_parent) in local_uid_map:
                        parent_uid_val = local_uid_map[str(raw_parent)]
                    elif raw_parent:
                        try:
                            parent_uid_val = int(raw_parent)
                        except (ValueError, TypeError):
                            parent_uid_val = None
                    else:
                        parent_uid_val = None
                    assigned_uid = self._next_uid(cursor, "BidPageFolders")
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
                for page in updates.get("pages", []):
                    if page.get("width") is None:
                        continue
                    if page.get("uid") is None:
                        raw_folder = page.get("folder_uid")
                        if raw_folder and str(raw_folder) in local_uid_map:
                            folder_uid_val = local_uid_map[str(raw_folder)]
                        elif raw_folder:
                            try:
                                folder_uid_val = int(raw_folder)
                            except (ValueError, TypeError):
                                folder_uid_val = None
                        else:
                            folder_uid_val = None
                        new_guid = "{" + str(uuid.uuid4()).upper() + "}"
                        assigned_page_uid = self._next_uid(cursor, "BidPages")
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
                                "OverlayImagePath": self._windows_path_separators(
                                    page.get("overlay_path")
                                ),
                                "OverlayRect": (
                                    default_overlay_rect(page["width"], page["height"])
                                    if page.get("overlay_path")
                                    else ""
                                ),
                                "BidPageFolderUID": folder_uid_val,
                            },
                            ("UID", "BidUID"),
                            "save_cover_sheet_new_page",
                        )
                    else:
                        folder_uid_val = (
                            int(page["folder_uid"]) if page.get("folder_uid") else None
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
                                "OverlayImagePath": self._windows_path_separators(
                                    page.get("overlay_path")
                                ),
                                "OverlayRect": (
                                    default_overlay_rect(page["width"], page["height"])
                                    if page.get("overlay_path")
                                    else ""
                                ),
                                "BidPageFolderUID": folder_uid_val,
                                "Sequence": page.get("sequence") or 1,
                            },
                            ("UID",),
                            "[UID]=?",
                            [int(page["uid"])],
                            "save_cover_sheet_page",
                        )
                return True
        except Exception:
            self.logger.exception(
                "Failed to save cover sheet for bid %s in %s", bid_uid, db_path
            )
            return False

    def delete_pages(self, db_path: str, page_uids: list[str]) -> bool:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                cursor = conn.cursor()
                for page_uid in page_uids:
                    self._delete_page_cascade(cursor, schema, int(page_uid))
                return True
        except Exception:
            self.logger.exception("Failed to delete pages in %s", db_path)
            return False

    def update_bid_job_status(
        self, db_path: str, bid_uid: str, job_status_uid: str | None
    ) -> bool:
        try:
            bid_uid_int = int(bid_uid)
            status_uid = (
                int(job_status_uid)
                if job_status_uid not in (None, "", "NULL")
                else None
            )
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                cursor = conn.cursor()
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
        except Exception:
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
                not schema.optional_table_missing(child)
                and not schema.optional_table_missing("BidTakeoffs")
                and schema.column_exists(child, "BidTakeoffFromUID")
                and schema.column_exists("BidTakeoffs", "UID")
                and schema.column_exists("BidTakeoffs", "BidPageUID")
            ):
                cursor.execute(
                    f"DELETE FROM [{child}] WHERE [BidTakeoffFromUID] IN "
                    "(SELECT [UID] FROM [BidTakeoffs] WHERE [BidPageUID] = ?)",
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
        for table in ("BidTakeoffTotals", "BidTypicalGroupTotals"):
            try:
                if schema.optional_table_missing(table) or not schema.column_exists(
                    table, "BidPageUID"
                ):
                    continue
                cursor.execute(
                    f"DELETE FROM [{table}] WHERE [BidPageUID] = ?", page_int
                )
            except pyodbc.Error as exc:
                self.logger.warning(
                    "Failed to delete from %s for page %s: %s", table, page_int, exc
                )
        if not schema.optional_table_missing("BidSettings") and schema.column_exists(
            "BidSettings", "BidPageSelectedUID"
        ):
            cursor.execute(
                "UPDATE [BidSettings] SET [BidPageSelectedUID]=NULL "
                "WHERE [BidPageSelectedUID]=?",
                page_int,
            )
        self._require_write_columns(schema, "BidPages", ("UID",))
        cursor.execute("DELETE FROM [BidPages] WHERE [UID]=?", page_int)

    def save_job_statuses(self, db_path: str, changes: dict) -> bool:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                if schema.optional_table_missing("JobStatuses"):
                    raise RuntimeError(
                        "This OST database does not support job statuses."
                    )
                cursor = conn.cursor()
                for uid in changes.get("deleted_uids", []):
                    try:
                        uid_int = int(uid)
                        if not schema.optional_table_missing(
                            "Bids"
                        ) and schema.column_exists("Bids", "JobStatusUID"):
                            cursor.execute(
                                "UPDATE [Bids] SET [JobStatusUID]=NULL WHERE [JobStatusUID]=?",
                                uid_int,
                            )
                        self._require_write_columns(schema, "JobStatuses", ("UID",))
                        cursor.execute(
                            "DELETE FROM [JobStatuses] WHERE [UID]=?", uid_int
                        )
                    except (pyodbc.Error, ValueError):
                        pass
                for s in changes.get("updated", []):
                    uid = s.get("uid")
                    if uid is None:
                        continue
                    try:
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
                            [int(uid)],
                            "save_job_status",
                        )
                    except (pyodbc.Error, ValueError):
                        pass
                for s in changes.get("new", []):
                    try:
                        locked_val = -1 if s.get("locked") else 0
                        self._execute_insert_values(
                            cursor,
                            schema,
                            "JobStatuses",
                            {
                                "UID": self._next_uid(cursor, "JobStatuses"),
                                "Name": s.get("name", "New Status"),
                                "Locked": locked_val,
                                "Sequence": s.get("sequence", 0),
                            },
                            ("UID", "Name"),
                            "save_job_status_new",
                        )
                    except pyodbc.Error:
                        pass
                return True
        except Exception:
            self.logger.exception("Failed to save job statuses in %s", db_path)
            return False

    def save_employees(self, db_path: str, changes: dict) -> dict | None:
        uid_map: dict = {}
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                if schema.optional_table_missing("Employees"):
                    raise RuntimeError("This OST database does not support employees.")
                cursor = conn.cursor()
                for uid in changes.get("deleted_uids", []):
                    try:
                        uid_int = int(uid)
                        if not schema.optional_table_missing(
                            "BidDPCSubscribers"
                        ) and schema.column_exists(
                            "BidDPCSubscribers", "BidEmployeeUID"
                        ):
                            cursor.execute(
                                "DELETE FROM [BidDPCSubscribers] WHERE [BidEmployeeUID]=?",
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
                            self.logger.warning(
                                "Failed to clear ConditionSets.EmployeeUID for %s: %s",
                                uid_int,
                                exc,
                            )
                        self._require_write_columns(schema, "Employees", ("UID",))
                        cursor.execute("DELETE FROM [Employees] WHERE [UID]=?", uid_int)
                    except (pyodbc.Error, ValueError) as exc:
                        self.logger.warning(
                            "Failed to delete employee %s: %s", uid, exc
                        )
                for e in changes.get("updated", []):
                    uid = e.uid
                    if uid is None:
                        continue
                    try:
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
                            [int(uid)],
                            "save_employee",
                        )
                    except (pyodbc.Error, ValueError):
                        pass
                for e in changes.get("new", []):
                    try:
                        raw_pc_uid = e.pay_class_uid
                        pc_uid_val = (
                            int(raw_pc_uid)
                            if raw_pc_uid and not str(raw_pc_uid).startswith("new_")
                            else None
                        )
                        assigned_uid = self._next_uid(cursor, "Employees")
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
                    except (pyodbc.Error, ValueError):
                        pass
                return uid_map
        except Exception:
            self.logger.exception("Failed to save employees in %s", db_path)
            return None

    def save_pay_classes(self, db_path: str, changes: dict) -> dict:
        uid_map: dict = {}
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                if schema.optional_table_missing("PayClasses"):
                    raise RuntimeError(
                        "This OST database does not support pay classes."
                    )
                cursor = conn.cursor()
                for uid in changes.get("deleted_uids", []):
                    try:
                        uid_int = int(uid)
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
                        self._require_write_columns(schema, "PayClasses", ("UID",))
                        cursor.execute(
                            "DELETE FROM [PayClasses] WHERE [UID]=?", uid_int
                        )
                    except (pyodbc.Error, ValueError) as exc:
                        self.logger.warning(
                            "Failed to delete pay class %s: %s", uid, exc
                        )
                for pc in changes.get("updated", []):
                    uid = pc.get("uid")
                    if uid is None:
                        continue
                    try:
                        self._execute_update_values(
                            cursor,
                            schema,
                            "PayClasses",
                            {"Name": pc.get("name", "")},
                            ("UID", "Name"),
                            "[UID]=?",
                            [int(uid)],
                            "save_pay_class",
                        )
                    except (pyodbc.Error, ValueError):
                        pass
                for pc in changes.get("new", []):
                    temp_uid = str(pc.get("uid", ""))
                    try:
                        assigned_uid = self._next_uid(cursor, "PayClasses")
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
                        uid_map[temp_uid] = str(assigned_uid)
                    except pyodbc.Error:
                        pass
                return uid_map
        except Exception:
            self.logger.exception("Failed to save pay classes in %s", db_path)
            return {}

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
                for uid in changes.get("deleted_uids", []):
                    try:
                        uid_int = int(uid)
                        self._require_write_columns(schema, "CdnTypes", ("UID",))
                        if not schema.optional_table_missing(
                            "BidConditions"
                        ) and schema.column_exists("BidConditions", "CdnTypeUID"):
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
                        cursor.execute("DELETE FROM [CdnTypes] WHERE [UID]=?", uid_int)
                    except (pyodbc.Error, ValueError) as exc:
                        self.logger.warning(
                            "Failed to delete condition type %s: %s", uid, exc
                        )
                for item in changes.get("updated", []):
                    uid = item.get("uid")
                    if uid is None:
                        continue
                    try:
                        self._execute_update_values(
                            cursor,
                            schema,
                            "CdnTypes",
                            {"Name": item.get("name", "")},
                            ("UID", "Name"),
                            "[UID]=?",
                            [int(uid)],
                            "save_condition_type",
                        )
                    except (pyodbc.Error, ValueError):
                        pass
                for item in changes.get("new", []):
                    temp_uid = str(item.get("uid", ""))
                    try:
                        assigned_uid = self._next_uid(cursor, "CdnTypes")
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
                    except pyodbc.Error:
                        pass
                return uid_map
        except Exception:
            self.logger.exception("Failed to save condition types in %s", db_path)
            return {}

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
                        try:
                            if not schema.optional_table_missing(
                                "BidTimeCards"
                            ) and schema.column_exists("BidTimeCards", "BidAreaUID"):
                                cursor.execute(
                                    "DELETE FROM [BidTimeCards] WHERE [BidAreaUID]=?",
                                    uid_int,
                                )
                        except pyodbc.Error:
                            pass
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
                        except pyodbc.Error:
                            pass
                        self._require_write_columns(schema, "BidAreas", ("UID",))
                        cursor.execute("DELETE FROM [BidAreas] WHERE [UID]=?", uid_int)
                    except (pyodbc.Error, ValueError):
                        pass
                for area in changes.updated:
                    try:
                        parent_val = int(area.parent_uid) if area.parent_uid else None
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
                    except (pyodbc.Error, ValueError):
                        pass
                for area in changes.new:
                    try:
                        if area.parent_uid and area.parent_uid in uid_map:
                            parent_val = int(uid_map[area.parent_uid])
                        elif area.parent_uid and not area.parent_uid.startswith("new_"):
                            parent_val = int(area.parent_uid)
                        else:
                            parent_val = None
                        new_guid = "{" + str(uuid.uuid4()).upper() + "}"
                        assigned_uid = self._next_uid(cursor, "BidAreas")
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
                    except pyodbc.Error:
                        pass
        except Exception:
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
                if page_val is not None:
                    self._require_write_columns(schema, "BidPages", ("UID",))
                    cursor.execute("SELECT UID FROM [BidPages] WHERE UID=?", page_val)
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
        except Exception:
            self.logger.exception(
                "Failed to save bid selected page for bid %s in %s",
                bid_uid,
                db_path,
            )
            return False
