import datetime
from typing import Any, Callable, Dict, Optional, Set, Tuple
import pyodbc
from ....domain.dtos.raw_bid_data_dto import RawBidData
from ..schema_contract import PAGE_SECTIONS, RAW_BID_TABLES
from .connection_wrapper import ConnWrapper
from .constants import BID_TABLES_WRITE_ORDER, NUMERIC_TYPE_SUBSTRINGS


class ImportOperationsMixin:
    def import_ost_data(
        self,
        db_path: str,
        raw_data: RawBidData,
        transform_fn: Callable[
            [RawBidData, int, Dict[str, str], Dict[str, str]], RawBidData
        ],
        target_project_uid: Optional[str] = None,
    ) -> bool:
        try:
            with self._connection(db_path) as conn:
                max_uid = self._get_max_uid(conn)
                cdn_uid_map, max_uid = self._resolve_cdn_types(conn, raw_data, max_uid)
                job_status_uid_map, max_uid = self._resolve_job_statuses(
                    conn, raw_data, max_uid
                )
                remapped = transform_fn(
                    raw_data, max_uid, cdn_uid_map, job_status_uid_map
                )
                self._assign_next_bid_no(conn, remapped)
                if target_project_uid:
                    remapped.bid_row["BidProjectUID"] = target_project_uid
                else:
                    remapped.bid_row["BidProjectUID"] = None
                self._write_to_db(conn, remapped)
                return True
        except Exception:
            self.logger.exception("Failed to write imported OST data to %s", db_path)
            return False

    def _get_max_uid(self, connection: ConnWrapper) -> int:
        max_uid = 0
        tables_to_check = (
            ["Bids", "CdnTypes", "JobStatuses"] + RAW_BID_TABLES + list(PAGE_SECTIONS)
        )
        cursor = connection.cursor()
        try:
            for table in tables_to_check:
                try:
                    cursor.execute(f"SELECT MAX(UID) FROM [{table}]")
                    row = cursor.fetchone()
                    if row and row[0] is not None:
                        val = int(row[0])
                        if val > max_uid:
                            max_uid = val
                except pyodbc.Error:
                    pass
        finally:
            cursor.close()
        return max_uid

    def _assign_next_bid_no(
        self, connection: ConnWrapper, remapped: RawBidData
    ) -> None:
        next_bid_no = 1
        schema = self._schema(connection)
        if schema.optional_table_missing("Settings"):
            remapped.bid_row["BidNo"] = str(next_bid_no)
            return
        if not schema.column_exists("Settings", "NextBidNo"):
            schema.log_optional_write_skip(
                "Settings", "NextBidNo", "assign_next_bid_no"
            )
            remapped.bid_row["BidNo"] = str(next_bid_no)
            return
        cursor = connection.cursor()
        try:
            cursor.execute("SELECT [NextBidNo] FROM [Settings]")
            row = cursor.fetchone()
            if row and row[0] is not None:
                next_bid_no = int(row[0])
            cursor.execute("UPDATE [Settings] SET [NextBidNo] = ?", next_bid_no + 1)
        except pyodbc.Error:
            pass
        finally:
            cursor.close()
        remapped.bid_row["BidNo"] = str(next_bid_no)

    def _resolve_cdn_types(
        self,
        connection: ConnWrapper,
        raw_data: RawBidData,
        max_uid: int,
    ) -> Tuple[Dict[str, str], int]:
        cdn_uid_map: Dict[str, str] = {}
        incoming = raw_data.global_tables.get("CdnTypes", [])
        if not incoming:
            return cdn_uid_map, max_uid
        existing_by_name = self._load_existing_uid_by_name(connection, "CdnTypes")
        next_uid = max_uid + 1
        table_info = self._get_table_info(connection, "CdnTypes")
        for cdn_row in incoming:
            old_uid = cdn_row.get("UID", "")
            name = cdn_row.get("Name", "")
            if name in existing_by_name:
                cdn_uid_map[old_uid] = existing_by_name[name]
            else:
                new_uid = str(next_uid)
                next_uid += 1
                cdn_uid_map[old_uid] = new_uid
                existing_by_name[name] = new_uid
                insert_row = dict(cdn_row)
                insert_row["UID"] = new_uid
                self._insert_raw_row(connection, "CdnTypes", insert_row, table_info)
        return cdn_uid_map, next_uid - 1

    def _resolve_job_statuses(
        self,
        connection: ConnWrapper,
        raw_data: RawBidData,
        max_uid: int,
    ) -> Tuple[Dict[str, str], int]:
        job_status_uid_map: Dict[str, str] = {}
        incoming = raw_data.global_tables.get("JobStatuses", [])
        if not incoming:
            return job_status_uid_map, max_uid
        existing_by_name = self._load_existing_uid_by_name(connection, "JobStatuses")
        next_uid = max_uid + 1
        table_info = self._get_table_info(connection, "JobStatuses")
        for js_row in incoming:
            old_uid = js_row.get("UID", "")
            name = js_row.get("Name", "")
            if name in existing_by_name:
                job_status_uid_map[old_uid] = existing_by_name[name]
            else:
                new_uid = str(next_uid)
                next_uid += 1
                job_status_uid_map[old_uid] = new_uid
                existing_by_name[name] = new_uid
                insert_row = dict(js_row)
                insert_row["UID"] = new_uid
                self._insert_raw_row(connection, "JobStatuses", insert_row, table_info)
        return job_status_uid_map, next_uid - 1

    def _write_to_db(
        self,
        connection: ConnWrapper,
        remapped: RawBidData,
    ) -> None:
        table_info = self._get_table_info(connection, "Bids")
        self._insert_raw_row(connection, "Bids", remapped.bid_row, table_info)
        for table in BID_TABLES_WRITE_ORDER:
            rows = remapped.bid_tables.get(table, [])
            if not rows:
                continue
            table_info = self._get_table_info(connection, table)
            for row in rows:
                try:
                    self._insert_raw_row(connection, table, row, table_info)
                except Exception as exc:
                    self.logger.error(
                        "Failed inserting into [%s], row=%s, error=%s", table, row, exc
                    )
                    raise
        for table in PAGE_SECTIONS:
            rows = remapped.page_tables.get(table, [])
            if not rows:
                continue
            table_info = self._get_table_info(connection, table)
            for row in rows:
                try:
                    self._insert_raw_row(connection, table, row, table_info)
                except Exception as exc:
                    self.logger.error(
                        "Failed inserting into [%s], row=%s, error=%s", table, row, exc
                    )
                    raise

    def _load_existing_uid_by_name(
        self, connection: ConnWrapper, table: str
    ) -> Dict[str, str]:
        schema = self._schema(connection)
        if schema.optional_table_missing(table):
            return {}
        if not schema.column_exists(table, "UID") or not schema.column_exists(
            table, "Name"
        ):
            return {}
        existing_by_name: Dict[str, str] = {}
        cursor = connection.cursor()
        try:
            cursor.execute(f"SELECT [UID], [Name] FROM [{table}]")
            for row in cursor.fetchall():
                uid_val = str(row[0]) if row[0] is not None else ""
                name_val = str(row[1]) if row[1] is not None else ""
                existing_by_name[name_val] = uid_val
        except pyodbc.Error:
            pass
        finally:
            cursor.close()
        return existing_by_name

    def _get_table_info(
        self, connection: ConnWrapper, table: str
    ) -> Tuple[Set[str], Dict[str, str]]:
        return (
            self._get_table_columns(connection, table),
            self._get_column_types(connection, table),
        )

    def _get_table_columns(self, connection: ConnWrapper, table: str) -> Set[str]:
        cols: Set[str] = set()
        cursor = connection.cursor()
        try:
            rows = cursor.columns(table=table).fetchall()
            for col in rows:
                cols.add(col.column_name)
        except pyodbc.Error:
            pass
        finally:
            cursor.close()
        return cols

    def _get_column_types(self, connection: ConnWrapper, table: str) -> Dict[str, str]:
        types: Dict[str, str] = {}
        cursor = connection.cursor()
        try:
            rows = cursor.columns(table=table).fetchall()
            for col in rows:
                types[col.column_name] = (col.type_name or "").lower()
        except pyodbc.Error:
            pass
        finally:
            cursor.close()
        return types

    def _insert_raw_row(
        self,
        connection: ConnWrapper,
        table: str,
        row: Dict[str, str],
        table_info: Tuple[Set[str], Dict[str, str]],
    ) -> None:
        db_columns, col_types = table_info
        filtered = {k: v for k, v in row.items() if k in db_columns}
        if not filtered:
            return
        cols = list(filtered.keys())
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(f"[{c}]" for c in cols)
        values = [
            self._convert_access_value(filtered[column], col_types.get(column, ""))
            for column in cols
        ]
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"INSERT INTO [{table}] ({col_names}) VALUES ({placeholders})",
                values,
            )
        finally:
            cursor.close()

    def _convert_access_value(self, value: str, type_name: str) -> Any:
        if value is None or value == "NULL":
            return None
        if type_name == "yesno":
            if value in ("True", "true", "-1", "1"):
                return -1
            return 0
        if type_name == "datetime":
            if not value or value == "":
                return None
            try:
                parts = value.split()
                if len(parts) == 6:
                    return datetime.datetime(
                        int(parts[0]),
                        int(parts[1]),
                        int(parts[2]),
                        int(parts[3]),
                        int(parts[4]),
                        int(parts[5]),
                    )
            except (ValueError, TypeError):
                pass
            return None
        if "longbinary" in type_name or "memo" in type_name:
            if not value or value == "":
                return None
            return value.encode("utf-8")
        is_numeric = any(t in type_name for t in NUMERIC_TYPE_SUBSTRINGS)
        if is_numeric:
            if value == "":
                return None
            if value == "0":
                return 0
            try:
                if "." in value:
                    return float(value)
                return int(value)
            except (ValueError, TypeError):
                return None
        return value
