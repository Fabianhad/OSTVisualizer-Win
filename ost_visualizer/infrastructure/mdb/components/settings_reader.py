from typing import Dict, List, Optional, Tuple
import pyodbc
from ...database.settings_cardinality import (
    fetch_optional_global_settings_row,
    normalize_next_bid_number,
)
from ...database.master_data_identity import require_unique_master_data_uids
from ...database.bid_owned_identity import (
    require_acyclic_bid_owned_parent_graph,
    require_valid_unique_bid_owned_uids,
)
from ....domain.entities.area import BidArea
from ....domain.entities.cover_sheet import (
    CoverSheetData,
    CoverSheetFolder,
    CoverSheetPage,
    JobStatus,
)
from ....domain.entities.employee import Employee, PayClass
from ...parsers.utils.parser import decode_value, parse_float
from .constants import LAYER_REFERENCE_TABLES


def _clean_optional_text(value):
    return "" if value in (None, "NULL") else value


class SettingsReaderMixin:
    def _parse_used_job_status_uids(self, connection) -> set[str]:
        schema = self._schema(connection)
        if schema.optional_table_missing("Bids") or not schema.column_exists(
            "Bids", "JobStatusUID"
        ):
            return set()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT DISTINCT [JobStatusUID] FROM [Bids] "
                "WHERE [JobStatusUID] IS NOT NULL"
            )
            return {str(row[0]) for row in cursor.fetchall() if row[0] is not None}

    def _parse_used_employee_uids(self, connection) -> set[str]:
        schema = self._schema(connection)
        if schema.optional_table_missing("Bids"):
            return set()
        role_columns = tuple(
            column
            for column in ("EstimatorUID", "PrManagerUID", "JobSiteManagerUID")
            if schema.column_exists("Bids", column)
        )
        if not role_columns:
            return set()
        selected_columns = ", ".join(f"[{column}]" for column in role_columns)
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT {selected_columns} FROM [Bids]")
            return {
                str(row[index])
                for row in cursor.fetchall()
                for index in range(len(role_columns))
                if row[index] is not None
            }

    def _parse_job_statuses(self, connection) -> List[JobStatus]:
        rows = self._select_all_unfiltered(connection, "JobStatuses")
        require_unique_master_data_uids((row.get("UID") for row in rows), "JobStatuses")
        return sorted(
            [
                JobStatus(
                    uid=_clean_optional_text(row.get("UID", "")),
                    name=_clean_optional_text(row.get("Name", "")),
                    locked=row.get("Locked", "0") not in ("0", "False", ""),
                    sequence=int(row.get("Sequence") or 0),
                )
                for row in rows
            ],
            key=lambda status: status.sequence,
        )

    def _parse_employees_and_pay_classes(
        self, connection
    ) -> Tuple[List[Employee], List[PayClass]]:
        employee_rows = self._select_all_unfiltered(connection, "Employees")
        pay_class_rows = self._select_all_unfiltered(connection, "PayClasses")
        require_unique_master_data_uids(
            (row.get("UID") for row in employee_rows), "Employees"
        )
        require_unique_master_data_uids(
            (row.get("UID") for row in pay_class_rows), "PayClasses"
        )
        employees = [
            Employee(
                uid=_clean_optional_text(row.get("UID", "")),
                employee_no=_clean_optional_text(row.get("EmployeeNo", "")),
                first_name=_clean_optional_text(row.get("FirstName", "")),
                last_name=_clean_optional_text(row.get("LastName", "")),
                address1=_clean_optional_text(row.get("Address1", "")),
                address2=_clean_optional_text(row.get("Address2", "")),
                city=_clean_optional_text(row.get("City", "")),
                state=_clean_optional_text(row.get("State", "")),
                zip=_clean_optional_text(row.get("Zip", "")),
                home_phone=_clean_optional_text(row.get("HomePhone", "")),
                mobile_phone=_clean_optional_text(row.get("MobilePhone", "")),
                email=_clean_optional_text(row.get("EMail", "")),
                pay_class_uid=_clean_optional_text(row.get("PayClassUID", "")),
            )
            for row in employee_rows
        ]
        pay_classes = [
            PayClass(
                uid=_clean_optional_text(row.get("UID", "")),
                name=_clean_optional_text(row.get("Name", "")),
            )
            for row in pay_class_rows
        ]
        return employees, pay_classes

    def get_cover_sheet_data(
        self, file_path: str, bid_uid: str
    ) -> Optional[CoverSheetData]:
        with self._connection(file_path) as connection:
            return self._parse_cover_sheet_data(connection, bid_uid)

    def _parse_cover_sheet_data(
        self, connection, bid_uid: str
    ) -> Optional[CoverSheetData]:
        bid_row = self._select_all_single(connection, "Bids", "UID", bid_uid)
        if not bid_row:
            return None
        job_statuses = self._parse_job_statuses(connection)
        employees, pay_classes = self._parse_employees_and_pay_classes(connection)
        folders, pages_without_folder = self._query_cover_sheet_pages(
            connection, bid_uid
        )

        def safe_int(value, default):
            try:
                return int(value) if value not in (None, "", "NULL") else default
            except (ValueError, TypeError):
                return default

        return CoverSheetData(
            bid_uid=bid_uid,
            job_status_uid=_clean_optional_text(bid_row.get("JobStatusUID", "")),
            job_name=_clean_optional_text(bid_row.get("JobName", "")),
            estimator_uid=_clean_optional_text(bid_row.get("EstimatorUID", "")),
            notes=_clean_optional_text(bid_row.get("Notes", "")),
            bid_date=_clean_optional_text(bid_row.get("BidDate", "")),
            bid_no=_clean_optional_text(bid_row.get("BidNo", "")),
            job_id=_clean_optional_text(bid_row.get("JobID", "")),
            measure_base=safe_int(bid_row.get("MeasureBase"), 0),
            takeoff_increments=parse_float(bid_row.get("TakeoffIncrements"), 1.0),
            scale_style=safe_int(bid_row.get("ScaleStyle"), 1),
            scale_factor1=parse_float(bid_row.get("ScaleFactor1"), 0.25),
            scale_factor2=parse_float(bid_row.get("ScaleFactor2"), 12.0),
            page_width=parse_float(bid_row.get("PageWidth"), 42.0),
            page_height=parse_float(bid_row.get("PageHeight"), 30.0),
            folders=folders,
            pages_without_folder=pages_without_folder,
            job_statuses=job_statuses,
            employees=employees,
            pay_classes=pay_classes,
            used_job_status_uids=self._parse_used_job_status_uids(connection),
        )

    def _query_cover_sheet_pages(
        self, connection: "pyodbc.Connection", bid_uid: str
    ) -> Tuple[Dict[str, CoverSheetFolder], List[CoverSheetPage]]:
        all_folders: Dict[str, CoverSheetFolder] = {}
        folder_parent_map: Dict[str, Optional[str]] = {}
        pages_without_folder: List[CoverSheetPage] = []
        try:
            schema = self._schema(connection)
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
                    folder_rows = cursor.fetchall()
                    require_valid_unique_bid_owned_uids(
                        (row.UID for row in folder_rows), "BidPageFolders"
                    )
                    for row in folder_rows:
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
                    require_acyclic_bid_owned_parent_graph(
                        folder_parent_map,
                        "BidPageFolders",
                    )
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
                        schema.optional_column("BidPages", "MultiPageCount", "0"),
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
                page_rows = cursor.fetchall()
                require_valid_unique_bid_owned_uids(
                    (row.UID for row in page_rows), "BidPages"
                )
                for row in page_rows:
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
                        multi_page_count=(
                            int(row.MultiPageCount)
                            if row.MultiPageCount is not None
                            else 0
                        ),
                    )
                    folder_uid = (
                        str(row.BidPageFolderUID) if row.BidPageFolderUID else None
                    )
                    if folder_uid and folder_uid in all_folders:
                        all_folders[folder_uid].pages.append(page)
                    else:
                        pages_without_folder.append(page)
            return root_folders, pages_without_folder
        except pyodbc.Error as exc:
            if self._record_caught_read_error(exc):
                raise
            return {}, []

    def get_settings_defaults(self, file_path: str) -> Dict:
        try:
            with self._connection(file_path) as connection:
                return self._parse_settings_defaults(connection)
        except (pyodbc.Error, TypeError, ValueError) as exc:
            if self._record_caught_read_error(exc, file_path):
                raise
            return self._settings_defaults()

    @staticmethod
    def _settings_defaults() -> Dict:
        return {
            "scale_style": 1,
            "scale_factor1": 0.125,
            "scale_factor2": 12.0,
            "page_width": 42.0,
            "page_height": 30.0,
            "measure_base": 0,
            "takeoff_increments": 1.0,
            "next_bid_no": 1,
        }

    def _parse_settings_defaults(self, connection) -> Dict:
        defaults = self._settings_defaults()
        schema = self._schema(connection)
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
        with connection.cursor() as cursor:
            row = fetch_optional_global_settings_row(cursor, settings_select)
            if row:
                defaults["scale_style"] = row.ScaleStyle or 1
                defaults["scale_factor1"] = row.ScaleFactor1 or 0.125
                defaults["scale_factor2"] = row.ScaleFactor2 or 12.0
                defaults["page_width"] = row.PageWidth or 42.0
                defaults["page_height"] = row.PageHeight or 30.0
                defaults["measure_base"] = row.MeasureBase or 0
                defaults["takeoff_increments"] = row.TakeoffIncrements or 1.0
                defaults["next_bid_no"] = normalize_next_bid_number(row.NextBidNo)
        return defaults

    def get_job_statuses(self, file_path: str) -> List[JobStatus]:
        try:
            with self._connection(file_path) as conn:
                return self._parse_job_statuses(conn)
        except Exception as exc:
            if self._record_caught_read_error(exc, file_path):
                raise
            self.logger.warning("Could not load job statuses from %s", file_path)
            return []

    def get_employees_and_pay_classes(
        self, file_path: str
    ) -> Tuple[List[Employee], List[PayClass]]:
        try:
            with self._connection(file_path) as conn:
                return self._parse_employees_and_pay_classes(conn)
        except Exception as exc:
            if self._record_caught_read_error(exc, file_path):
                raise
            self.logger.warning(
                "Could not load employees/pay classes from %s", file_path
            )
            return [], []

    def get_bid_areas(self, file_path: str, bid_uid: str) -> List[BidArea]:
        try:
            with self._connection(file_path) as conn:
                schema = self._schema(conn)
                return list(
                    self._parse_bid_areas_for_bid(conn, bid_uid, schema).values()
                )
        except Exception as exc:
            if self._record_caught_read_error(exc, file_path):
                raise
            self.logger.warning(
                "Could not load bid areas for bid %s from %s", bid_uid, file_path
            )
            return []

    def get_employee_uids_in_use(self, file_path: str) -> set:
        try:
            with self._connection(file_path) as connection:
                return self._parse_used_employee_uids(connection)
        except (pyodbc.Error, TypeError, ValueError) as e:
            if self._record_caught_read_error(e, file_path):
                raise
            self.logger.warning("Could not query employee UIDs in use: %s", e)
            return set()

    def get_condition_type_uids_in_use(self, file_path: str) -> set:
        try:
            with self._connection(file_path) as connection:
                schema = self._schema(connection)
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
        except (pyodbc.Error, TypeError, ValueError) as e:
            if self._record_caught_read_error(e, file_path):
                raise
            self.logger.warning("Could not query condition type UIDs in use: %s", e)
            return set()

    def get_layer_uids_in_use(self, file_path: str, bid_uid: str) -> set:
        try:
            with self._connection(file_path) as connection:
                schema = self._schema(connection)
                used_uids = set()
                with connection.cursor() as cursor:
                    for table in LAYER_REFERENCE_TABLES:
                        if schema.optional_table_missing(
                            table
                        ) or not schema.column_exists(table, "BidLayerUID"):
                            continue
                        if schema.column_exists(table, "BidUID"):
                            cursor.execute(
                                f"SELECT DISTINCT [BidLayerUID] FROM [{table}] "
                                "WHERE [BidUID] = ? AND [BidLayerUID] IS NOT NULL",
                                int(bid_uid),
                            )
                        else:
                            cursor.execute(
                                f"SELECT DISTINCT [BidLayerUID] FROM [{table}] "
                                "WHERE [BidLayerUID] IS NOT NULL"
                            )
                        used_uids.update(
                            str(row.BidLayerUID)
                            for row in cursor.fetchall()
                            if row.BidLayerUID is not None
                        )
                return used_uids
        except (pyodbc.Error, TypeError, ValueError) as e:
            if self._record_caught_read_error(e, file_path):
                raise
            self.logger.warning("Could not query layer UIDs in use: %s", e)
            return set()
