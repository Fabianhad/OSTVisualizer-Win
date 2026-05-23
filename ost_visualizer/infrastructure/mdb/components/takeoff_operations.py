import uuid
from typing import List
from ....application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from .constants import encode_position


class TakeoffOperationsMixin:
    _TAKEOFF_TYPED_COLUMNS = frozenset(
        {
            "UID",
            "BidUID",
            "BidConditionUID",
            "BidPageUID",
            "BidAreaUID",
            "Position",
            "Rotation",
            "Curve",
            "ParentUID",
            "IsNegativeQuantity",
        }
    )
    _TAKEOFF_BID_SCOPED_FKS = frozenset(
        {
            "BidZoneUID",
            "BidTypAreaUID",
            "TypGroupTakeoffUID",
            "TypPageTakeoffUID",
            "TypGroupUID",
            "TypGroupMarkerUID",
        }
    )

    def save_takeoffs_area(
        self, db_path: str, takeoff_uids: List[str], area_uid: str
    ) -> bool:
        try:
            area_val = None if area_uid in ("0", "", None) else int(area_uid)
        except (TypeError, ValueError):
            self.logger.exception(
                "Invalid area uid for takeoff assignment: %s", area_uid
            )
            return False
        return self._save_takeoffs_value(
            db_path,
            takeoff_uids,
            "BidAreaUID",
            area_val,
            "takeoffs area",
        )

    def save_takeoffs_condition(
        self, db_path: str, takeoff_uids: List[str], condition_uid: str
    ) -> bool:
        try:
            condition_val = int(condition_uid)
        except (TypeError, ValueError):
            self.logger.exception(
                "Invalid condition uid for takeoff assignment: %s", condition_uid
            )
            return False
        return self._save_takeoffs_value(
            db_path,
            takeoff_uids,
            "BidConditionUID",
            condition_val,
            "takeoffs condition",
        )

    def _save_takeoffs_value(
        self,
        db_path: str,
        takeoff_uids: List[str],
        column: str,
        value,
        label: str,
    ) -> bool:
        if not takeoff_uids:
            return True
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "BidTakeoffs", ("UID", column))
                cursor = conn.cursor()
                placeholders = ",".join("?" * len(takeoff_uids))
                uid_ints = [int(u) for u in takeoff_uids]
                cursor.execute(
                    f"UPDATE [BidTakeoffs] SET [{column}]=? "
                    f"WHERE [UID] IN ({placeholders})",
                    [value] + uid_ints,
                )
                return True
        except Exception:
            self.logger.exception("Failed to save %s in %s", label, db_path)
            return False

    def set_takeoffs_negative(
        self, db_path: str, takeoff_uids: List[str], is_negative: bool
    ) -> bool:
        if not takeoff_uids:
            return True
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(
                    schema, "BidTakeoffs", ("UID", "IsNegativeQuantity")
                )
                cursor = conn.cursor()
                placeholders = ",".join("?" * len(takeoff_uids))
                uid_ints = [int(u) for u in takeoff_uids]
                cursor.execute(
                    f"UPDATE [BidTakeoffs] SET [IsNegativeQuantity]=? WHERE [UID] IN ({placeholders})",
                    [is_negative] + uid_ints,
                )
                return True
        except Exception:
            self.logger.exception(
                "Failed to save takeoffs negative flag in %s", db_path
            )
            return False

    def set_takeoff_curve(
        self,
        db_path: str,
        takeoff_uid: str,
        position: List[float],
        curve: int,
    ) -> bool:
        try:
            position_bytes = encode_position(position)
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "BidTakeoffs", ("UID", "Position"))
                cursor = conn.cursor()
                self._execute_update_values(
                    cursor,
                    schema,
                    "BidTakeoffs",
                    {"Position": position_bytes, "Curve": curve},
                    ("Position",),
                    "[UID]=?",
                    [int(takeoff_uid)],
                    "set_takeoff_curve",
                )
                return True
        except Exception:
            self.logger.exception("Failed to set takeoff curve in %s", db_path)
            return False

    def save_takeoff_positions(self, db_path: str, positions: List[tuple]) -> bool:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "BidTakeoffs", ("UID", "Position"))
                cursor = conn.cursor()
                for takeoff_uid, position in positions:
                    cursor.execute(
                        "UPDATE [BidTakeoffs] SET [Position]=? WHERE [UID]=?",
                        encode_position(position),
                        int(takeoff_uid),
                    )
                return True
        except Exception:
            self.logger.exception(
                "Failed to bulk save takeoff positions in %s", db_path
            )
            return False

    def save_takeoff_rotations(self, db_path: str, rotations: List[tuple]) -> bool:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "BidTakeoffs", ("UID", "Rotation"))
                cursor = conn.cursor()
                for takeoff_uid, rotation in rotations:
                    cursor.execute(
                        "UPDATE [BidTakeoffs] SET [Rotation]=? WHERE [UID]=?",
                        rotation,
                        int(takeoff_uid),
                    )
                return True
        except Exception:
            self.logger.exception(
                "Failed to bulk save takeoff rotations in %s", db_path
            )
            return False

    def delete_takeoffs(self, db_path: str, takeoff_uids: List[str]) -> bool:
        if not takeoff_uids:
            return True
        try:
            uids = [int(u) for u in takeoff_uids]
        except (TypeError, ValueError):
            self.logger.exception(
                "Invalid takeoff uids passed to delete_takeoffs: %s", takeoff_uids
            )
            return False
        placeholders = ",".join("?" * len(uids))
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "BidTakeoffs", ("UID",))
                cursor = conn.cursor()
                for child in ("BidDimensions", "BidALines", "BidArrows"):
                    if schema.optional_table_missing(child) or not schema.column_exists(
                        child, "BidTakeoffFromUID"
                    ):
                        continue
                    cursor.execute(
                        f"DELETE FROM [{child}] WHERE [BidTakeoffFromUID] IN "
                        f"({placeholders})",
                        *uids,
                    )
                if not schema.optional_table_missing(
                    "BidPercents"
                ) and schema.column_exists("BidPercents", "BidTakeoffUID"):
                    cursor.execute(
                        f"DELETE FROM [BidPercents] WHERE [BidTakeoffUID] IN "
                        f"({placeholders})",
                        *uids,
                    )
                cursor.execute(
                    f"DELETE FROM [BidTakeoffs] WHERE [UID] IN ({placeholders})",
                    *uids,
                )
                return True
        except Exception:
            self.logger.exception("Failed to delete takeoffs in %s", db_path)
            return False

    def insert_takeoffs(
        self,
        db_path: str,
        bid_uid: str,
        takeoff_specs: List[InsertTakeoffSpec],
    ) -> List[str]:
        if not takeoff_specs:
            return []
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(
                    schema,
                    "BidTakeoffs",
                    ("UID", "BidUID", "BidConditionUID", "BidPageUID", "Position"),
                )
                cursor = conn.cursor()
                table_cols = sorted(schema.get_columns("BidTakeoffs"))
                table_col_set = set(table_cols)
                new_uids = []
                for spec in takeoff_specs:
                    position_bytes = encode_position(spec.position)
                    area_val = (
                        None
                        if not spec.area_uid or spec.area_uid in ("0", "")
                        else int(spec.area_uid)
                    )
                    parent_val = (
                        int(spec.parent_uid)
                        if spec.parent_uid and spec.parent_uid not in ("0", "")
                        else 0
                    )
                    cursor.execute("SELECT MAX([UID]) FROM [BidTakeoffs]")
                    row = cursor.fetchone()
                    new_uid = (int(row[0]) + 1) if row and row[0] is not None else 1
                    typed_values = {
                        "UID": new_uid,
                        "BidUID": int(bid_uid),
                        "BidConditionUID": int(spec.condition_uid),
                        "BidPageUID": int(spec.page_uid),
                        "BidAreaUID": area_val,
                        "Position": position_bytes,
                        "Rotation": spec.rotation,
                        "Curve": spec.curve,
                        "ParentUID": parent_val,
                        "IsNegativeQuantity": spec.is_negative,
                    }
                    if spec.raw_extras:
                        cross_bid = spec.source_bid_uid is not None and str(
                            spec.source_bid_uid
                        ) != str(bid_uid)
                        for col_name, col_val in spec.raw_extras.items():
                            if col_name in self._TAKEOFF_TYPED_COLUMNS:
                                continue
                            if col_name not in table_col_set:
                                continue
                            if cross_bid and col_name in self._TAKEOFF_BID_SCOPED_FKS:
                                typed_values[col_name] = None
                            elif col_name == "GUID":
                                typed_values[col_name] = (
                                    "{" + str(uuid.uuid4()).upper() + "}"
                                )
                            else:
                                typed_values[col_name] = col_val
                    self._execute_insert_values(
                        cursor,
                        schema,
                        "BidTakeoffs",
                        typed_values,
                        ("UID", "BidUID", "BidConditionUID", "BidPageUID", "Position"),
                        "insert_takeoffs",
                    )
                    new_uids.append(str(new_uid))
                return new_uids
        except Exception:
            self.logger.exception("Failed to bulk insert takeoffs in %s", db_path)
            return []
