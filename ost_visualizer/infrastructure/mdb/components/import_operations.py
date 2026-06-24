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
            [
                RawBidData,
                int,
                Dict[str, str],
                Dict[str, str],
                Dict[str, str],
                Dict[str, str],
            ],
            RawBidData,
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
                access_level_uid_map = self._resolve_access_levels(conn, raw_data)
                pay_class_uid_map = self._resolve_pay_classes(conn, raw_data)
                employee_uid_map = self._resolve_employees(
                    conn,
                    raw_data,
                    pay_class_uid_map,
                    access_level_uid_map,
                )
                remapped = transform_fn(
                    raw_data,
                    max_uid,
                    cdn_uid_map,
                    job_status_uid_map,
                    employee_uid_map,
                    pay_class_uid_map,
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

    def _resolve_access_levels(
        self,
        connection: ConnWrapper,
        raw_data: RawBidData,
    ) -> Dict[str, str]:
        access_level_uid_map: Dict[str, str] = {}
        incoming = raw_data.global_tables.get("AccessLevels", [])
        if not incoming:
            return access_level_uid_map
        schema = self._schema(connection)
        if schema.optional_table_missing("AccessLevels"):
            return access_level_uid_map
        existing_by_description = self._load_existing_uid_by_column(
            connection, "AccessLevels", "Description"
        )
        next_uid = self._next_table_uid(connection, "AccessLevels")
        table_info = self._get_table_info(connection, "AccessLevels")
        for row in incoming:
            old_uid = row.get("UID", "")
            description = row.get("Description", "")
            if description and description in existing_by_description:
                access_level_uid_map[old_uid] = existing_by_description[description]
                continue
            new_uid = str(next_uid)
            next_uid += 1
            access_level_uid_map[old_uid] = new_uid
            if description:
                existing_by_description[description] = new_uid
            insert_row = dict(row)
            insert_row["UID"] = new_uid
            self._insert_raw_row(connection, "AccessLevels", insert_row, table_info)
        return access_level_uid_map

    def _resolve_pay_classes(
        self,
        connection: ConnWrapper,
        raw_data: RawBidData,
    ) -> Dict[str, str]:
        pay_class_uid_map: Dict[str, str] = {}
        incoming = raw_data.global_tables.get("PayClasses", [])
        if not incoming:
            return pay_class_uid_map
        schema = self._schema(connection)
        if schema.optional_table_missing("PayClasses"):
            return pay_class_uid_map
        existing_by_name = self._load_existing_uid_by_name(connection, "PayClasses")
        next_uid = self._next_table_uid(connection, "PayClasses")
        table_info = self._get_table_info(connection, "PayClasses")
        for row in incoming:
            old_uid = row.get("UID", "")
            name = row.get("Name", "")
            if name and name in existing_by_name:
                pay_class_uid_map[old_uid] = existing_by_name[name]
                continue
            new_uid = str(next_uid)
            next_uid += 1
            pay_class_uid_map[old_uid] = new_uid
            if name:
                existing_by_name[name] = new_uid
            insert_row = dict(row)
            insert_row["UID"] = new_uid
            self._insert_raw_row(connection, "PayClasses", insert_row, table_info)
        return pay_class_uid_map

    def _resolve_employees(
        self,
        connection: ConnWrapper,
        raw_data: RawBidData,
        pay_class_uid_map: Dict[str, str],
        access_level_uid_map: Dict[str, str],
    ) -> Dict[str, str]:
        employee_uid_map: Dict[str, str] = {}
        incoming = raw_data.global_tables.get("Employees", [])
        if not incoming:
            return employee_uid_map
        schema = self._schema(connection)
        if schema.optional_table_missing("Employees"):
            return employee_uid_map
        existing_by_key = self._load_existing_employee_uid_by_key(connection)
        next_uid = self._next_table_uid(connection, "Employees")
        table_info = self._get_table_info(connection, "Employees")
        for row in incoming:
            old_uid = row.get("UID", "")
            employee_key = self._employee_identity_key(row)
            if employee_key and employee_key in existing_by_key:
                employee_uid_map[old_uid] = existing_by_key[employee_key]
                continue
            new_uid = str(next_uid)
            next_uid += 1
            employee_uid_map[old_uid] = new_uid
            if employee_key:
                existing_by_key[employee_key] = new_uid
            insert_row = dict(row)
            insert_row["UID"] = new_uid
            pay_class_uid = insert_row.get("PayClassUID", "")
            if pay_class_uid:
                insert_row["PayClassUID"] = pay_class_uid_map.get(pay_class_uid, "NULL")
            access_level_uid = insert_row.get("AccessLevelUID", "")
            if access_level_uid:
                insert_row["AccessLevelUID"] = access_level_uid_map.get(
                    access_level_uid, "NULL"
                )
            self._insert_raw_row(connection, "Employees", insert_row, table_info)
        return employee_uid_map

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
        return self._load_existing_uid_by_column(connection, table, "Name")

    def _load_existing_uid_by_column(
        self, connection: ConnWrapper, table: str, column: str
    ) -> Dict[str, str]:
        schema = self._schema(connection)
        if schema.optional_table_missing(table):
            return {}
        if not schema.column_exists(table, "UID") or not schema.column_exists(
            table, column
        ):
            return {}
        existing_by_value: Dict[str, str] = {}
        cursor = connection.cursor()
        try:
            cursor.execute(f"SELECT [UID], [{column}] FROM [{table}]")
            for row in cursor.fetchall():
                uid_val = str(row[0]) if row[0] is not None else ""
                column_val = str(row[1]) if row[1] is not None else ""
                existing_by_value[column_val] = uid_val
        except pyodbc.Error:
            pass
        finally:
            cursor.close()
        return existing_by_value

    def _load_existing_employee_uid_by_key(
        self, connection: ConnWrapper
    ) -> Dict[str, str]:
        schema = self._schema(connection)
        if schema.optional_table_missing("Employees"):
            return {}
        if not schema.column_exists("Employees", "UID"):
            return {}
        columns = [
            column
            for column in ("UID", "EmployeeNo", "FirstName", "LastName", "EMail")
            if schema.column_exists("Employees", column)
        ]
        if "UID" not in columns:
            return {}
        existing_by_key: Dict[str, str] = {}
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"SELECT {', '.join(f'[{column}]' for column in columns)} "
                "FROM [Employees]"
            )
            for row in cursor.fetchall():
                row_data = {
                    columns[index]: str(row[index]) if row[index] is not None else ""
                    for index in range(len(columns))
                }
                key = self._employee_identity_key(row_data)
                if key:
                    existing_by_key[key] = row_data["UID"]
        except pyodbc.Error:
            pass
        finally:
            cursor.close()
        return existing_by_key

    def _employee_identity_key(self, row: Dict[str, str]) -> str:
        employee_no = (row.get("EmployeeNo") or "").strip().casefold()
        if employee_no:
            return f"no:{employee_no}"
        first_name = (row.get("FirstName") or "").strip().casefold()
        last_name = (row.get("LastName") or "").strip().casefold()
        email = (row.get("EMail") or "").strip().casefold()
        if first_name or last_name or email:
            return f"name:{first_name}|{last_name}|{email}"
        return ""

    def _next_table_uid(self, connection: ConnWrapper, table: str) -> int:
        cursor = connection.cursor()
        try:
            cursor.execute(f"SELECT MAX([UID]) FROM [{table}]")
            row = cursor.fetchone()
            if row and row[0] is not None:
                return int(row[0]) + 1
        except pyodbc.Error:
            pass
        finally:
            cursor.close()
        return 1

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
        filtered = {
            column: value
            for column, value in filtered.items()
            if not self._should_omit_autonumber_uid(column, value, col_types)
        }
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

    def _should_omit_autonumber_uid(
        self, column: str, value: str, col_types: Dict[str, str]
    ) -> bool:
        return (
            column == "UID"
            and col_types.get(column, "") == "counter"
            and value in (None, "", "0", "NULL")
        )

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
