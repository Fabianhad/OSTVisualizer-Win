import uuid
from dataclasses import asdict
from types import MappingProxyType
from typing import Dict, List, Optional
from ....application.dtos.create_condition_spec_dto import CreateConditionSpec
from ....application.dtos.update_condition_dto import UpdateConditionDto
from .serialization import coerce_binary_column_value, encode_text_blob


class ConditionOperationsMixin:
    _CONDITION_CROSS_BID_CLEAR_COLUMNS = frozenset(
        {
            "BidConditionFolderUID",
            "BidLayerUID",
        }
    )

    @staticmethod
    def _new_ost_guid() -> str:
        return "{" + str(uuid.uuid4()).upper() + "}"

    def _allocate_condition_identity(self, cursor, bid_uid: str):
        schema = self._schema(cursor.connection)
        self._require_write_columns(schema, "BidConditions", ("UID", "BidUID"))
        new_uid = self._next_uid(cursor, "BidConditions")
        new_guid = self._new_ost_guid()
        max_ref = None
        if schema.column_exists("BidConditions", "RefNo"):
            cursor.execute(
                "SELECT MAX([RefNo]) FROM [BidConditions] WHERE [BidUID] = ?",
                int(bid_uid),
            )
            max_ref = cursor.fetchone()[0]
        next_ref_no = (int(max_ref) + 1) if max_ref is not None else 1
        return new_uid, new_guid, next_ref_no

    def duplicate_conditions(
        self, db_path: str, bid_uid: str, condition_uids: List[str]
    ) -> List[str]:
        if not condition_uids:
            return []
        new_uids: List[str] = []
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "BidConditions", ("UID", "BidUID"))
                cursor = conn.cursor()
                for condition_uid in condition_uids:
                    table_cols = sorted(schema.get_columns("BidConditions"))
                    select_cols = ", ".join(f"[{c}]" for c in table_cols)
                    cursor.execute(
                        f"SELECT {select_cols} FROM [BidConditions] "
                        "WHERE [UID] = ? AND [BidUID] = ?",
                        condition_uid,
                        bid_uid,
                    )
                    cols = [d[0] for d in cursor.description]
                    binary_cols = {
                        d[0] for d in cursor.description if d[1] is bytearray
                    }
                    source_row = cursor.fetchone()
                    if not source_row:
                        continue
                    row_data = dict(zip(cols, source_row))
                    new_uid, new_guid, next_ref_no = self._allocate_condition_identity(
                        cursor, bid_uid
                    )
                    row_data["UID"] = new_uid
                    if "GUID" in row_data:
                        row_data["GUID"] = new_guid
                    if "RefNo" in row_data:
                        row_data["RefNo"] = next_ref_no
                    values = []
                    for c in cols:
                        val = row_data[c]
                        if c in binary_cols and val is not None:
                            val = coerce_binary_column_value(val)
                        values.append(val)
                    self._execute_insert_values(
                        cursor,
                        schema,
                        "BidConditions",
                        dict(zip(cols, values)),
                        ("UID", "BidUID"),
                        "duplicate_conditions",
                    )
                    new_uids.append(str(new_uid))
            return new_uids
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception("Failed to duplicate conditions in %s", db_path)
            return []

    def duplicate_conditions_to_bid(
        self,
        db_path: str,
        source_bid_uid: str,
        destination_bid_uid: str,
        condition_uids: List[str],
    ) -> Dict[str, str]:
        if not condition_uids:
            return {}
        ordered_uids = list(dict.fromkeys(str(uid) for uid in condition_uids if uid))
        if not ordered_uids:
            return {}
        uid_map: Dict[str, str] = {}
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "BidConditions", ("UID", "BidUID"))
                cursor = conn.cursor()
                table_cols = sorted(schema.get_columns("BidConditions"))
                select_cols = ", ".join(f"[{c}]" for c in table_cols)
                for condition_uid in ordered_uids:
                    cursor.execute(
                        f"SELECT {select_cols} FROM [BidConditions] "
                        "WHERE [UID] = ? AND [BidUID] = ?",
                        int(condition_uid),
                        int(source_bid_uid),
                    )
                    cols = [d[0] for d in cursor.description]
                    binary_cols = {
                        d[0] for d in cursor.description if d[1] is bytearray
                    }
                    source_row = cursor.fetchone()
                    if not source_row:
                        raise ValueError(
                            f"Condition {condition_uid} was not found in bid "
                            f"{source_bid_uid}"
                        )
                    row_data = dict(zip(cols, source_row))
                    old_uid = str(int(row_data["UID"]))
                    new_uid, new_guid, next_ref_no = self._allocate_condition_identity(
                        cursor, destination_bid_uid
                    )
                    row_data["UID"] = new_uid
                    row_data["BidUID"] = int(destination_bid_uid)
                    if "GUID" in row_data:
                        row_data["GUID"] = new_guid
                    if "RefNo" in row_data:
                        row_data["RefNo"] = next_ref_no
                    for col in self._CONDITION_CROSS_BID_CLEAR_COLUMNS:
                        if col in row_data:
                            row_data[col] = None
                    values = []
                    for c in cols:
                        val = row_data[c]
                        if c in binary_cols and val is not None:
                            val = coerce_binary_column_value(val)
                        values.append(val)
                    self._execute_insert_values(
                        cursor,
                        schema,
                        "BidConditions",
                        dict(zip(cols, values)),
                        ("UID", "BidUID"),
                        "duplicate_conditions_to_bid",
                    )
                    uid_map[old_uid] = str(new_uid)
            return uid_map
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception(
                "Failed to duplicate conditions from bid %s to bid %s in %s",
                source_bid_uid,
                destination_bid_uid,
                db_path,
            )
            return {}

    def insert_condition(
        self, db_path: str, bid_uid: str, spec: CreateConditionSpec
    ) -> Optional[str]:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                cursor = conn.cursor()
                new_uid, new_guid, next_ref_no = self._allocate_condition_identity(
                    cursor, bid_uid
                )
                _FIXED_COLS = [
                    "UID",
                    "BidUID",
                    "GUID",
                    "RefNo",
                    "IsTemplate",
                    "Curve",
                    "SnapToGrid",
                    "ManualLength",
                    "MatAmount",
                    "LabAmount",
                    "SubAmount",
                    "FontName",
                    "FontSize",
                    "FontBold",
                    "FontItalic",
                    "ShowTakeoff",
                ]
                _RESERVED = set(_FIXED_COLS) | {"Backout"}
                values_by_col = dict(
                    zip(
                        _FIXED_COLS,
                        [
                            new_uid,
                            int(bid_uid),
                            new_guid,
                            next_ref_no,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                            "Arial",
                            -16,
                            0,
                            0,
                            -1,
                        ],
                    )
                )
                values_by_col["Backout"] = -1 if spec.backout else 0
                for field_name, val in asdict(spec).items():
                    col = self._FIELD_TO_COLUMN.get(field_name)
                    if col is None or col in _RESERVED:
                        continue
                    if col == "Notes":
                        val = encode_text_blob(val) if val else None
                    elif col in ("CdnTypeUID", "BidLayerUID", "BidConditionFolderUID"):
                        val = int(val) if val else None
                    values_by_col[col] = val
                self._execute_insert_values(
                    cursor,
                    schema,
                    "BidConditions",
                    values_by_col,
                    ("UID", "BidUID", "Name", "Type"),
                    "insert_condition",
                )
                return str(new_uid)
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception("Failed to insert condition in %s", db_path)
            return None

    def delete_conditions(
        self, db_path: str, bid_uid: str, condition_uids: List[str]
    ) -> bool:
        if not condition_uids:
            return True
        try:
            cond_ints = [int(u) for u in condition_uids]
            bid_int = int(bid_uid)
        except (TypeError, ValueError) as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.warning(
                "Invalid uids passed to delete_conditions: bid=%s conds=%s",
                bid_uid,
                condition_uids,
            )
            return False
        placeholders = ",".join("?" * len(cond_ints))
        takeoff_subquery = (
            "(SELECT [UID] FROM [BidTakeoffs] "
            f"WHERE [BidConditionUID] IN ({placeholders}) AND [BidUID] = ?)"
        )
        sub_params = (*cond_ints, bid_int)
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "BidConditions", ("UID", "BidUID"))
                cursor = conn.cursor()
                for child in ("BidDimensions", "BidALines", "BidArrows"):
                    if schema.optional_table_missing(child) or not schema.column_exists(
                        child, "BidTakeoffFromUID"
                    ):
                        continue
                    cursor.execute(
                        f"DELETE FROM [{child}] WHERE [BidTakeoffFromUID] IN "
                        f"{takeoff_subquery}",
                        *sub_params,
                    )
                if not schema.optional_table_missing(
                    "BidPercents"
                ) and schema.column_exists("BidPercents", "BidTakeoffUID"):
                    cursor.execute(
                        f"DELETE FROM [BidPercents] WHERE [BidTakeoffUID] IN "
                        f"{takeoff_subquery}",
                        *sub_params,
                    )
                if not schema.optional_table_missing("BidTakeoffs"):
                    self._require_write_columns(
                        schema, "BidTakeoffs", ("BidConditionUID", "BidUID")
                    )
                    cursor.execute(
                        f"DELETE FROM [BidTakeoffs] WHERE [BidConditionUID] IN "
                        f"({placeholders}) AND [BidUID] = ?",
                        *cond_ints,
                        bid_int,
                    )
                if not schema.optional_table_missing(
                    "BidLaborActivity"
                ) and schema.column_exists("BidLaborActivity", "BidConditionUID"):
                    cursor.execute(
                        f"DELETE FROM [BidLaborActivity] WHERE [BidConditionUID] IN "
                        f"({placeholders}) AND [BidUID] = ?",
                        *cond_ints,
                        bid_int,
                    )
                try:
                    if not schema.optional_table_missing(
                        "ConditionSetStyles"
                    ) and schema.column_exists(
                        "ConditionSetStyles", "ConditionStyleUID"
                    ):
                        cursor.execute(
                            f"DELETE FROM [ConditionSetStyles] WHERE [ConditionStyleUID] IN "
                            f"({placeholders})",
                            *cond_ints,
                        )
                except Exception as exc:
                    if self._record_caught_mutation_error(exc):
                        raise
                    self.logger.warning(
                        "Failed to clear ConditionSetStyles for conditions %s: %s",
                        cond_ints,
                        exc,
                    )
                cursor.execute(
                    f"DELETE FROM [BidConditions] WHERE [UID] IN ({placeholders}) "
                    "AND [BidUID] = ?",
                    *cond_ints,
                    bid_int,
                )
                return True
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception(
                "Failed to delete conditions %s in %s", condition_uids, db_path
            )
            return False

    _FIELD_TO_COLUMN: Dict[str, str] = MappingProxyType(
        {
            "name": "Name",
            "condition_type": "Type",
            "backout": "Backout",
            "ref_no": "RefNo",
            "cdn_type_uid": "CdnTypeUID",
            "layer_uid": "BidLayerUID",
            "height": "Height",
            "width": "Width",
            "depth": "Depth",
            "thickness": "Thickness",
            "rise": "Rise",
            "run": "Run",
            "display_size": "DisplaySize",
            "shape": "Shape",
            "pattern": "Pattern",
            "spacing": "Spacing",
            "color_fill": "ColorFill",
            "uom1": "UOM1",
            "uom2": "UOM2",
            "uom3": "UOM3",
            "calc_type1": "Quantity1",
            "calc_type2": "Quantity2",
            "calc_type3": "Quantity3",
            "notes": "Notes",
            "drop_run": "DropRun",
            "drop_value": "DropValue",
            "round_quantity": "RoundQuantity",
            "round_up": "RoundUp",
            "trim": "Trim",
            "is_curved_segment": "IsCurvedSegment",
            "grid": "Grid",
            "grid_size1": "GridSize1",
            "grid_size2": "GridSize2",
            "gap": "Gap",
            "display_dimension": "DisplayDimension",
            "display_name": "DisplayName",
            "display_grid_while_drawing": "DisplayGridWhileDrawing",
            "folder_uid": "BidConditionFolderUID",
        }
    )

    def _shift_conflicting_ref_nos_for_update(
        self,
        cursor,
        schema,
        bid_uid: int,
        condition_uid: int,
        new_ref_no: int,
    ) -> None:
        self._require_write_columns(schema, "BidConditions", ("UID", "BidUID", "RefNo"))
        cursor.execute(
            "SELECT [RefNo] FROM [BidConditions] WHERE [UID] = ? AND [BidUID] = ?",
            condition_uid,
            bid_uid,
        )
        current_row = cursor.fetchone()
        if current_row is None or int(current_row[0]) == new_ref_no:
            return
        cursor.execute(
            "SELECT [UID] FROM [BidConditions] "
            "WHERE [BidUID] = ? AND [RefNo] = ? AND [UID] <> ?",
            bid_uid,
            new_ref_no,
            condition_uid,
        )
        if cursor.fetchone() is None:
            return
        cursor.execute(
            "UPDATE [BidConditions] SET [RefNo] = [RefNo] + 1 "
            "WHERE [BidUID] = ? AND [RefNo] >= ? AND [UID] <> ?",
            bid_uid,
            new_ref_no,
            condition_uid,
        )

    def update_condition(
        self,
        db_path: str,
        bid_uid: str,
        condition_uid: str,
        updates: UpdateConditionDto,
    ) -> bool:
        changes = updates.get_changes()
        if not changes:
            return True
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                cursor = conn.cursor()
                values_by_col = {}
                for field_name, val in changes.items():
                    col_name = self._FIELD_TO_COLUMN.get(field_name)
                    if col_name is None:
                        continue
                    if col_name == "Notes":
                        val = encode_text_blob(val) if val else None
                    elif col_name == "CdnTypeUID":
                        val = int(val) if val else None
                    elif col_name in ("BidLayerUID", "BidConditionFolderUID"):
                        val = int(val) if val else None
                    elif col_name == "Backout":
                        val = -1 if val else 0
                    values_by_col[col_name] = val
                if not values_by_col:
                    return True
                bid_uid_int = int(bid_uid)
                condition_uid_int = int(condition_uid)
                if "RefNo" in values_by_col:
                    new_ref_no = int(values_by_col["RefNo"])
                    values_by_col["RefNo"] = new_ref_no
                    self._shift_conflicting_ref_nos_for_update(
                        cursor,
                        schema,
                        bid_uid_int,
                        condition_uid_int,
                        new_ref_no,
                    )
                self._execute_update_values(
                    cursor,
                    schema,
                    "BidConditions",
                    values_by_col,
                    ("UID", "BidUID"),
                    "[UID] = ? AND [BidUID] = ?",
                    [condition_uid_int, bid_uid_int],
                    "update_condition",
                )
                return True
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception(
                "Failed to update condition %s in %s", condition_uid, db_path
            )
            return False

    def renumber_conditions(
        self, db_path: str, bid_uid: str, ordered_condition_uids: List[str]
    ) -> bool:
        if not ordered_condition_uids:
            return True
        try:
            bid_int = int(bid_uid)
            uid_ints = [int(uid) for uid in ordered_condition_uids]
        except (TypeError, ValueError) as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.warning(
                "Invalid uids passed to renumber_conditions: bid=%s conds=%s",
                bid_uid,
                ordered_condition_uids,
            )
            return False
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(
                    schema, "BidConditions", ("UID", "BidUID", "RefNo")
                )
                cursor = conn.cursor()
                placeholders = ",".join("?" * len(uid_ints))
                cursor.execute(
                    f"SELECT [UID] FROM [BidConditions] "
                    f"WHERE [UID] IN ({placeholders}) AND [BidUID] = ?",
                    *uid_ints,
                    bid_int,
                )
                found_uids = {int(row[0]) for row in cursor.fetchall()}
                missing = [uid for uid in uid_ints if uid not in found_uids]
                if missing:
                    raise ValueError(f"Conditions {missing} not found in bid {bid_uid}")
                cursor.execute(
                    "SELECT MAX([RefNo]) FROM [BidConditions] WHERE [BidUID] = ?",
                    bid_int,
                )
                max_ref_no = cursor.fetchone()[0]
                temp_offset = int(max_ref_no or 0) + len(uid_ints) + 1
                for ref_no, condition_uid in enumerate(uid_ints, start=1):
                    cursor.execute(
                        "UPDATE [BidConditions] SET [RefNo] = ? "
                        "WHERE [UID] = ? AND [BidUID] = ?",
                        temp_offset + ref_no,
                        condition_uid,
                        bid_int,
                    )
                for ref_no, condition_uid in enumerate(uid_ints, start=1):
                    cursor.execute(
                        "UPDATE [BidConditions] SET [RefNo] = ? "
                        "WHERE [UID] = ? AND [BidUID] = ?",
                        ref_no,
                        condition_uid,
                        bid_int,
                    )
                return True
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception(
                "Failed to renumber conditions for bid %s in %s", bid_uid, db_path
            )
            return False
