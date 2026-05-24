from pathlib import Path
from typing import Dict, List, Tuple
from ....domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyFileEntry,
    HierarchyFolderInfo,
    HierarchyPageInfo,
    HierarchyProjectInfo,
)
from ...parsers.utils.parser import decode_value, parse_float, remove_empty_folders
from ..schema_compatibility import MdbSchemaInspector


class HierarchyReaderMixin:
    def _parse_hierarchy(
        self, connection: "pyodbc.Connection", file_path: str
    ) -> HierarchyFileEntry:
        database_name = Path(file_path).stem
        schema = MdbSchemaInspector(connection, self.logger)
        schema.require_column("BidProjects", "UID")
        schema.require_column("BidProjects", "Name")
        schema.require_column("Bids", "UID")
        schema.require_column("Bids", "JobName")
        schema.require_column("BidPages", "UID")
        schema.require_column("BidPages", "BidUID")
        schema.require_column("BidConditions", "UID")
        schema.require_column("BidConditions", "BidUID")
        with connection.cursor() as cursor:
            bid_projects: Dict[str, HierarchyProjectInfo] = {}
            orphan_bids: List[HierarchyBidInfo] = []
            project_description = schema.optional_column(
                "BidProjects", "Description", "NULL"
            )
            cursor.execute(
                f"SELECT [UID], [Name], {project_description} "
                "FROM [BidProjects] ORDER BY [Name], [UID]"
            )
            for project_uid, bid_name, description in cursor.fetchall():
                project_uid_str = str(project_uid)
                bid_projects[project_uid_str] = HierarchyProjectInfo(
                    name=decode_value(bid_name),
                    description=decode_value(description),
                )
            bid_select = ", ".join(
                [
                    "[UID]",
                    schema.optional_column("Bids", "BidProjectUID", "NULL"),
                    schema.optional_column("Bids", "OrigBidProjectUID", "NULL"),
                    "[JobName]",
                    schema.optional_column("Bids", "JobID", "NULL"),
                    schema.optional_column("Bids", "BidNo", "0"),
                    schema.optional_column("Bids", "BidDate", "NULL"),
                    schema.optional_column("Bids", "Notes", "NULL"),
                    schema.optional_column("Bids", "JobStatusUID", "NULL"),
                    schema.optional_column("Bids", "EstimatorUID", "NULL"),
                    schema.optional_column("Bids", "CopyFromBidNO", "0"),
                    schema.optional_column("Bids", "CopyTimeStamp", "NULL"),
                    schema.optional_column("Bids", "MeasureBase", "0"),
                    schema.optional_column("Bids", "TakeoffIncrements", "1"),
                ]
            )
            bid_order = schema.order_by_existing(
                "Bids", ("BidProjectUID", "BidNo", "UID"), "[UID]"
            )
            cursor.execute(
                f"""
                SELECT {bid_select}
                FROM [Bids]
                ORDER BY {bid_order}
                """
            )
            bid_rows = cursor.fetchall()
        status_map = self._load_status_map(connection)
        employee_map = self._load_employee_map(connection)
        for bid_row in bid_rows:
            bid_uid = str(bid_row.UID)
            project_uid = str(bid_row.BidProjectUID) if bid_row.BidProjectUID else None
            bid_name = decode_value(bid_row.JobName)
            folders, pages_without_folder = self._get_bid_folder_page_structure(
                connection, bid_uid, schema
            )
            raw_status_uid = str(bid_row.JobStatusUID)
            status_value = status_map.get(raw_status_uid, "")
            raw_estimator_uid = (
                str(bid_row.EstimatorUID) if bid_row.EstimatorUID else None
            )
            estimator_value = (
                employee_map.get(raw_estimator_uid, "") if raw_estimator_uid else ""
            )
            with connection.cursor() as page_cursor:
                page_cursor.execute(
                    "SELECT COUNT(*) FROM [BidPages] WHERE [BidUID] = ?", bid_uid
                )
                page_count = int(page_cursor.fetchone()[0])
            with connection.cursor() as condition_cursor:
                condition_cursor.execute(
                    "SELECT COUNT(*) FROM [BidConditions] WHERE [BidUID] = ?", bid_uid
                )
                condition_count = int(condition_cursor.fetchone()[0])
            bid_info = HierarchyBidInfo(
                uid=bid_uid,
                name=bid_name,
                job_id=decode_value(bid_row.JobID),
                bid_no=bid_row.BidNo,
                bid_date=bid_row.BidDate,
                notes=decode_value(bid_row.Notes),
                status=status_value,
                estimator=estimator_value,
                page_count=page_count,
                condition_count=condition_count,
                measure_base=int(bid_row.MeasureBase or 0),
                takeoff_increments=float(bid_row.TakeoffIncrements or 1.0),
                orig_bid_project_uid=(
                    str(bid_row.OrigBidProjectUID)
                    if bid_row.OrigBidProjectUID
                    else None
                ),
                copy_from_bid_no=int(bid_row.CopyFromBidNO or 0),
                copy_timestamp=bid_row.CopyTimeStamp,
                folders=folders,
                pages_without_folder=pages_without_folder,
            )
            if project_uid and project_uid in bid_projects:
                bid_projects[project_uid].bids.append(bid_info)
            else:
                orphan_bids.append(bid_info)
        return HierarchyFileEntry(
            file_path="",
            database_name=database_name,
            bid_projects=bid_projects,
            orphan_bids=orphan_bids,
        )

    def _get_bid_folder_page_structure(
        self,
        connection: "pyodbc.Connection",
        bid_uid: str,
        schema: MdbSchemaInspector,
    ) -> Tuple[Dict[str, HierarchyFolderInfo], List[HierarchyPageInfo]]:
        with connection.cursor() as cursor:
            pages_without_folder: List[HierarchyPageInfo] = []
            folder_rows = []
            if not schema.optional_table_missing("BidPageFolders"):
                schema.require_column("BidPageFolders", "UID")
                schema.require_column("BidPageFolders", "BidUID")
                schema.require_column("BidPageFolders", "Name")
                folder_description = schema.optional_column(
                    "BidPageFolders", "Description", "NULL"
                )
                folder_parent = schema.optional_column(
                    "BidPageFolders", "ParentUID", "NULL"
                )
                cursor.execute(
                    f"""
                    SELECT [UID], [Name], {folder_description}, {folder_parent}
                    FROM [BidPageFolders]
                    WHERE [BidUID] = ?
                    ORDER BY [Name], [UID]
                    """,
                    bid_uid,
                )
                folder_rows = cursor.fetchall()
            all_folders: Dict[str, HierarchyFolderInfo] = {}
            root_folders: Dict[str, HierarchyFolderInfo] = {}
            for folder_uid, folder_name, description, parent_uid in folder_rows:
                folder_uid_str = str(folder_uid)
                folder_data = HierarchyFolderInfo(
                    name=decode_value(folder_name),
                    description=decode_value(description),
                    parent_uid=(
                        str(parent_uid) if parent_uid and parent_uid != 0 else None
                    ),
                )
                all_folders[folder_uid_str] = folder_data
            for folder_uid_str, folder_data in all_folders.items():
                parent_uid = folder_data.parent_uid
                if parent_uid is None or parent_uid == "0":
                    root_folders[folder_uid_str] = folder_data
                elif parent_uid in all_folders:
                    all_folders[parent_uid].subfolders[folder_uid_str] = folder_data
            select_clause = ", ".join(
                schema.select_column_or_default("BidPages", column, default)
                for column, default in (
                    ("UID", "NULL"),
                    ("Name", "NULL"),
                    ("BidPageFolderUID", "NULL"),
                    ("SheetNo", "NULL"),
                    ("Sequence", "0"),
                    ("ImagePath", "NULL"),
                    ("Width", "0"),
                    ("Height", "0"),
                    ("ScaleFactor1", "1"),
                    ("ScaleFactor2", "1"),
                    ("Rotation", "0"),
                    ("FlipX", "0"),
                    ("FlipY", "0"),
                    ("Index1", "1"),
                )
            )
            order_clause = schema.order_by_existing(
                "BidPages", ("Sequence", "Name", "UID"), "[UID]"
            )
            cursor.execute(
                f"""
                SELECT {select_clause}
                FROM [BidPages]
                WHERE [BidUID] = ?
                ORDER BY {order_clause}
                """,
                bid_uid,
            )
            for row in cursor.fetchall():
                page_uid_str = str(row.UID)
                page_name_str = decode_value(row.Name)
                page_info = HierarchyPageInfo(
                    uid=page_uid_str,
                    name=page_name_str,
                    sheet_no=decode_value(row.SheetNo) or "",
                    sequence=int(row.Sequence or 0),
                    image_path=decode_value(row.ImagePath) or None,
                    width=parse_float(row.Width),
                    height=parse_float(row.Height),
                    scale_factor1=parse_float(row.ScaleFactor1, 1.0),
                    scale_factor2=parse_float(row.ScaleFactor2, 1.0),
                    rotation=int(row.Rotation or 0),
                    flip_x=row.FlipX in (-1, True),
                    flip_y=row.FlipY in (-1, True),
                    page_index=max(0, int(row.Index1 or 1) - 1),
                )
                folder_uid = row.BidPageFolderUID
                if folder_uid and str(folder_uid) in all_folders:
                    all_folders[str(folder_uid)].pages.append(page_info)
                else:
                    pages_without_folder.append(page_info)
            folders = remove_empty_folders(root_folders)
            return folders, pages_without_folder

    def _load_status_map(self, connection: "pyodbc.Connection") -> Dict[str, str]:
        schema = MdbSchemaInspector(connection, self.logger)
        if schema.optional_table_missing("JobStatuses"):
            return {}
        schema.require_column("JobStatuses", "UID")
        schema.require_column("JobStatuses", "Name")
        with connection.cursor() as cursor:
            status_map: Dict[str, str] = {}
            cursor.execute("SELECT [UID], [Name] FROM [JobStatuses]")
            for row in cursor.fetchall():
                status_map[str(row.UID)] = decode_value(row.Name)
            return status_map

    def _load_employee_map(self, connection: "pyodbc.Connection") -> Dict[str, str]:
        schema = MdbSchemaInspector(connection, self.logger)
        if schema.optional_table_missing("Employees"):
            return {}
        schema.require_column("Employees", "UID")
        first_name = schema.optional_column("Employees", "FirstName", "NULL")
        last_name = schema.optional_column("Employees", "LastName", "NULL")
        with connection.cursor() as cursor:
            employee_map: Dict[str, str] = {}
            cursor.execute(f"SELECT [UID], {first_name}, {last_name} FROM [Employees]")
            for row in cursor.fetchall():
                first_name = decode_value(row.FirstName).strip()
                last_name = decode_value(row.LastName).strip()
                full_name = f"{first_name} {last_name}".strip()
                employee_map[str(row.UID)] = full_name
            return employee_map
