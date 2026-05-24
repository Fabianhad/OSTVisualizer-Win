from typing import Dict, List, Optional, Tuple
import pyodbc
from ....domain.entities.area import BidArea
from ....domain.entities.cover_sheet import (
    CoverSheetData,
    CoverSheetFolder,
    CoverSheetPage,
    JobStatus,
)
from ....domain.entities.employee import Employee, PayClass
from ...parsers.utils.parser import decode_value, parse_float
from ..schema_compatibility import MdbSchemaInspector


class SettingsReaderMixin:
    def get_cover_sheet_data(
        self, file_path: str, bid_uid: str
    ) -> Optional[CoverSheetData]:
        def _clean(val: str) -> str:
            return "" if val in (None, "NULL") else val

        with self._connection(file_path) as connection:
            bid_row = self._select_all_single(connection, "Bids", "UID", bid_uid)
            if not bid_row:
                return None
            js_rows = self._select_all_unfiltered(connection, "JobStatuses")
            job_statuses = sorted(
                [
                    JobStatus(
                        uid=_clean(r.get("UID", "")),
                        name=_clean(r.get("Name", "")),
                        locked=r.get("Locked", "0") not in ("0", "False", ""),
                        sequence=int(r.get("Sequence") or 0),
                    )
                    for r in js_rows
                ],
                key=lambda s: s.sequence,
            )
            emp_rows = self._select_all_unfiltered(connection, "Employees")
            employees = [
                Employee(
                    uid=_clean(r.get("UID", "")),
                    employee_no=_clean(r.get("EmployeeNo", "")),
                    first_name=_clean(r.get("FirstName", "")),
                    last_name=_clean(r.get("LastName", "")),
                    address1=_clean(r.get("Address1", "")),
                    address2=_clean(r.get("Address2", "")),
                    city=_clean(r.get("City", "")),
                    state=_clean(r.get("State", "")),
                    zip=_clean(r.get("Zip", "")),
                    home_phone=_clean(r.get("HomePhone", "")),
                    mobile_phone=_clean(r.get("MobilePhone", "")),
                    email=_clean(r.get("EMail", "")),
                    pay_class_uid=_clean(r.get("PayClassUID", "")),
                )
                for r in emp_rows
            ]
            pc_rows = self._select_all_unfiltered(connection, "PayClasses")
            pay_classes = [
                PayClass(uid=_clean(r.get("UID", "")), name=_clean(r.get("Name", "")))
                for r in pc_rows
            ]
            used_job_status_uids: set = set()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT DISTINCT [JobStatusUID] FROM [Bids]"
                        " WHERE [JobStatusUID] IS NOT NULL"
                    )
                    for row in cursor.fetchall():
                        val = str(row[0]).strip() if row[0] is not None else ""
                        if val and val != "NULL":
                            used_job_status_uids.add(val)
            except Exception:
                pass
            folders, pages_without_folder = self._query_cover_sheet_pages(
                connection, bid_uid
            )

            def _safe_float(val, default):
                try:
                    return float(val) if val not in (None, "", "NULL") else default
                except (ValueError, TypeError):
                    return default

            def _safe_int(val, default):
                try:
                    return int(val) if val not in (None, "", "NULL") else default
                except (ValueError, TypeError):
                    return default

            return CoverSheetData(
                bid_uid=bid_uid,
                job_status_uid=_clean(bid_row.get("JobStatusUID", "")),
                job_name=_clean(bid_row.get("JobName", "")),
                estimator_uid=_clean(bid_row.get("EstimatorUID", "")),
                notes=_clean(bid_row.get("Notes", "")),
                bid_date=_clean(bid_row.get("BidDate", "")),
                bid_no=_clean(bid_row.get("BidNo", "")),
                job_id=_clean(bid_row.get("JobID", "")),
                measure_base=_safe_int(bid_row.get("MeasureBase"), 0),
                takeoff_increments=_safe_float(bid_row.get("TakeoffIncrements"), 1.0),
                scale_style=_safe_int(bid_row.get("ScaleStyle"), 1),
                scale_factor1=_safe_float(bid_row.get("ScaleFactor1"), 0.25),
                scale_factor2=_safe_float(bid_row.get("ScaleFactor2"), 12.0),
                page_width=_safe_float(bid_row.get("PageWidth"), 42.0),
                page_height=_safe_float(bid_row.get("PageHeight"), 30.0),
                folders=folders,
                pages_without_folder=pages_without_folder,
                job_statuses=job_statuses,
                employees=employees,
                pay_classes=pay_classes,
                used_job_status_uids=used_job_status_uids,
            )

    def _query_cover_sheet_pages(
        self, connection: "pyodbc.Connection", bid_uid: str
    ) -> Tuple[Dict[str, CoverSheetFolder], List[CoverSheetPage]]:
        all_folders: Dict[str, CoverSheetFolder] = {}
        folder_parent_map: Dict[str, Optional[str]] = {}
        pages_without_folder: List[CoverSheetPage] = []
        try:
            schema = MdbSchemaInspector(connection, self.logger)
            schema.require_column("BidPages", "UID")
            schema.require_column("BidPages", "BidUID")
            with connection.cursor() as cursor:
                if not schema.optional_table_missing("BidPageFolders"):
                    schema.require_column("BidPageFolders", "UID")
                    schema.require_column("BidPageFolders", "BidUID")
                    schema.require_column("BidPageFolders", "Name")
                    parent_uid_col = schema.optional_column(
                        "BidPageFolders", "ParentUID", "NULL"
                    )
                    cursor.execute(
                        f"SELECT [UID], [Name], {parent_uid_col} "
                        "FROM [BidPageFolders] WHERE [BidUID] = ? ORDER BY [Name]",
                        bid_uid,
                    )
                    for row in cursor.fetchall():
                        folder_uid = str(row.UID)
                        parent_uid = (
                            str(row.ParentUID)
                            if (row.ParentUID and row.ParentUID != 0)
                            else None
                        )
                        all_folders[folder_uid] = CoverSheetFolder(
                            uid=folder_uid, name=decode_value(row.Name) or folder_uid
                        )
                        folder_parent_map[folder_uid] = parent_uid
            root_folders: Dict[str, CoverSheetFolder] = {}
            for folder_uid, folder in all_folders.items():
                parent_uid = folder_parent_map.get(folder_uid)
                if parent_uid and parent_uid in all_folders:
                    all_folders[parent_uid].subfolders[folder_uid] = folder
                else:
                    root_folders[folder_uid] = folder
            with connection.cursor() as cursor:
                page_select = ", ".join(
                    [
                        "[UID]",
                        schema.optional_column("BidPages", "Name", "NULL"),
                        schema.optional_column("BidPages", "SheetNo", "NULL"),
                        schema.optional_column("BidPages", "Width", "0"),
                        schema.optional_column("BidPages", "Height", "0"),
                        schema.optional_column("BidPages", "ScaleFactor1", "1"),
                        schema.optional_column("BidPages", "ScaleFactor2", "1"),
                        schema.optional_column("BidPages", "ImagePath", "NULL"),
                        schema.optional_column("BidPages", "OverlayImagePath", "NULL"),
                        schema.optional_column("BidPages", "Index1", "1"),
                        schema.optional_column("BidPages", "Show", "0"),
                        schema.optional_column("BidPages", "BidPageFolderUID", "NULL"),
                    ]
                )
                order_clause = schema.order_by_existing(
                    "BidPages", ("Sequence",), "[UID]"
                )
                cursor.execute(
                    f"""
                    SELECT {page_select}
                    FROM [BidPages]
                    WHERE [BidUID] = ?
                    ORDER BY {order_clause}
                    """,
                    bid_uid,
                )
                for row in cursor.fetchall():
                    page = CoverSheetPage(
                        uid=str(row.UID) if row.UID is not None else "",
                        sheet_no=decode_value(row.SheetNo) or "",
                        name=decode_value(row.Name) or "",
                        width=parse_float(row.Width),
                        height=parse_float(row.Height),
                        scale_factor1=parse_float(row.ScaleFactor1, 1.0),
                        scale_factor2=parse_float(row.ScaleFactor2, 1.0),
                        image_path=decode_value(row.ImagePath) or "",
                        overlay_image_path=decode_value(row.OverlayImagePath) or "",
                        index=int(row.Index1) if row.Index1 is not None else 1,
                        show_mode=int(row.Show) if row.Show is not None else 0,
                    )
                    folder_uid = (
                        str(row.BidPageFolderUID) if row.BidPageFolderUID else None
                    )
                    if folder_uid and folder_uid in all_folders:
                        all_folders[folder_uid].pages.append(page)
                    else:
                        pages_without_folder.append(page)
            return root_folders, pages_without_folder
        except pyodbc.Error:
            return {}, []

    def get_settings_defaults(self, file_path: str) -> Dict:
        defaults = {
            "scale_style": 1,
            "scale_factor1": 0.125,
            "scale_factor2": 12.0,
            "page_width": 42.0,
            "page_height": 30.0,
            "measure_base": 0,
            "takeoff_increments": 1.0,
            "next_bid_no": 1,
        }
        try:
            with self._connection(file_path) as conn:
                schema = MdbSchemaInspector(conn, self.logger)
                if schema.optional_table_missing("Settings"):
                    return defaults
                settings_select = ", ".join(
                    [
                        schema.optional_column("Settings", "ScaleStyle", "1"),
                        schema.optional_column("Settings", "ScaleFactor1", "0.125"),
                        schema.optional_column("Settings", "ScaleFactor2", "12"),
                        schema.optional_column("Settings", "PageWidth", "42"),
                        schema.optional_column("Settings", "PageHeight", "30"),
                        schema.optional_column("Settings", "MeasureBase", "0"),
                        schema.optional_column("Settings", "TakeoffIncrements", "1"),
                        schema.optional_column("Settings", "NextBidNo", "1"),
                    ]
                )
                with conn.cursor() as cursor:
                    cursor.execute(f"SELECT {settings_select} FROM [Settings]")
                    row = cursor.fetchone()
                    if row:
                        defaults["scale_style"] = row.ScaleStyle or 1
                        defaults["scale_factor1"] = row.ScaleFactor1 or 0.125
                        defaults["scale_factor2"] = row.ScaleFactor2 or 12.0
                        defaults["page_width"] = row.PageWidth or 42.0
                        defaults["page_height"] = row.PageHeight or 30.0
                        defaults["measure_base"] = row.MeasureBase or 0
                        defaults["takeoff_increments"] = row.TakeoffIncrements or 1.0
                        defaults["next_bid_no"] = (
                            int(row.NextBidNo) if row.NextBidNo else 1
                        )
        except Exception:
            pass
        return defaults

    def get_job_statuses(self, file_path: str) -> List[JobStatus]:
        def _clean(val):
            return "" if val in (None, "NULL") else val

        try:
            with self._connection(file_path) as conn:
                rows = self._select_all_unfiltered(conn, "JobStatuses")
            return sorted(
                [
                    JobStatus(
                        uid=_clean(r.get("UID", "")),
                        name=_clean(r.get("Name", "")),
                        locked=r.get("Locked", "0") not in ("0", "False", ""),
                        sequence=int(r.get("Sequence") or 0),
                    )
                    for r in rows
                ],
                key=lambda s: s.sequence,
            )
        except Exception:
            self.logger.warning("Could not load job statuses from %s", file_path)
            return []

    def get_employees_and_pay_classes(
        self, file_path: str
    ) -> Tuple[List[Employee], List[PayClass]]:
        def _clean(val):
            return "" if val in (None, "NULL") else val

        try:
            with self._connection(file_path) as conn:
                emp_rows = self._select_all_unfiltered(conn, "Employees")
                pc_rows = self._select_all_unfiltered(conn, "PayClasses")
            employees = [
                Employee(
                    uid=_clean(r.get("UID", "")),
                    employee_no=_clean(r.get("EmployeeNo", "")),
                    first_name=_clean(r.get("FirstName", "")),
                    last_name=_clean(r.get("LastName", "")),
                    address1=_clean(r.get("Address1", "")),
                    address2=_clean(r.get("Address2", "")),
                    city=_clean(r.get("City", "")),
                    state=_clean(r.get("State", "")),
                    zip=_clean(r.get("Zip", "")),
                    home_phone=_clean(r.get("HomePhone", "")),
                    mobile_phone=_clean(r.get("MobilePhone", "")),
                    email=_clean(r.get("EMail", "")),
                    pay_class_uid=_clean(r.get("PayClassUID", "")),
                )
                for r in emp_rows
            ]
            pay_classes = [
                PayClass(uid=_clean(r.get("UID", "")), name=_clean(r.get("Name", "")))
                for r in pc_rows
            ]
            return employees, pay_classes
        except Exception:
            self.logger.warning(
                "Could not load employees/pay classes from %s", file_path
            )
            return [], []

    def get_bid_areas(self, file_path: str, bid_uid: str) -> List[BidArea]:
        try:
            with self._connection(file_path) as conn:
                schema = MdbSchemaInspector(conn, self.logger)
                return list(
                    self._parse_bid_areas_for_bid(conn, bid_uid, schema).values()
                )
        except Exception:
            self.logger.warning(
                "Could not load bid areas for bid %s from %s", bid_uid, file_path
            )
            return []

    def get_estimator_uids_in_use(self, file_path: str) -> set:
        try:
            with self._connection(file_path) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT EstimatorUID FROM Bids WHERE EstimatorUID IS NOT NULL"
                    )
                    return {str(row.EstimatorUID) for row in cursor.fetchall()}
        except Exception as e:
            self.logger.warning("Could not query estimator UIDs in use: %s", e)
            return set()

    def get_condition_type_uids_in_use(self, file_path: str) -> set:
        try:
            with self._connection(file_path) as connection:
                schema = MdbSchemaInspector(connection, self.logger)
                if schema.optional_table_missing("BidConditions"):
                    return set()
                if not schema.column_exists("BidConditions", "CdnTypeUID"):
                    return set()
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT DISTINCT [CdnTypeUID] FROM [BidConditions] "
                        "WHERE [CdnTypeUID] IS NOT NULL"
                    )
                    return {str(row.CdnTypeUID) for row in cursor.fetchall()}
        except Exception as e:
            self.logger.warning("Could not query condition type UIDs in use: %s", e)
            return set()

    def get_layer_uids_in_use(self, file_path: str, bid_uid: str) -> set:
        try:
            with self._connection(file_path) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT DISTINCT [BidLayerUID] FROM [BidConditions] "
                        "WHERE [BidUID] = ? AND [BidLayerUID] IS NOT NULL",
                        int(bid_uid),
                    )
                    return {str(row.BidLayerUID) for row in cursor.fetchall()}
        except Exception as e:
            self.logger.warning("Could not query layer UIDs in use: %s", e)
            return set()
