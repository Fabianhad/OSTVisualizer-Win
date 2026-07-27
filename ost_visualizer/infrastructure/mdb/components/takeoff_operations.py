import uuid
from typing import List
from ....application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ....domain.entities.area import is_unassigned_area_uid
from .bulk_write_helpers import ACCESS_BULK_CHUNK_SIZE
from .constants import TAKEOFF_REFERENCE_TABLES
from .identity_allocation import AccessIdentityAllocationMixin
from .serialization import encode_position


class TakeoffOperationsMixin(AccessIdentityAllocationMixin):
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
    _TAKEOFF_TEXT_PROPERTY_COLUMNS = {
        "dimension_font_name": "FontName",
        "dimension_font_color": "FontColor",
        "dimension_font_size": "FontSize",
        "dimension_font_bold": "FontBold",
        "dimension_font_italic": "FontItalic",
        "dimension_font_underline": "FontUnderline",
        "name_font_name": "NameFontName",
        "name_font_color": "NameFontColor",
        "name_font_size": "NameFontSize",
        "name_font_bold": "NameFontBold",
        "name_font_italic": "NameFontItalic",
        "name_font_underline": "NameFontUnderline",
    }
    _SELECTED_TAKEOFF_UPDATE_COLUMNS = frozenset(
        {
            "BidAreaUID",
            "BidConditionUID",
            "IsNegativeQuantity",
        }
    )

    def save_takeoffs_area(
        self, db_path: str, takeoff_uids: List[str], area_uid: str
    ) -> bool:
        try:
            area_val = None if is_unassigned_area_uid(area_uid) else int(area_uid)
        except (TypeError, ValueError) as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.warning("Invalid area uid for takeoff assignment: %s", area_uid)
            return False
        return self._update_selected_takeoffs_value(
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
        except (TypeError, ValueError) as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.warning(
                "Invalid condition uid for takeoff assignment: %s", condition_uid
            )
            return False
        return self._update_selected_takeoffs_value(
            db_path,
            takeoff_uids,
            "BidConditionUID",
            condition_val,
            "takeoffs condition",
        )

    def _update_selected_takeoffs_value(
        self,
        db_path: str,
        takeoff_uids: List[str],
        column: str,
        value,
        label: str,
    ) -> bool:
        if column not in self._SELECTED_TAKEOFF_UPDATE_COLUMNS:
            self.logger.error("Unsupported selected takeoff update column: %s", column)
            return False
        try:
            uid_ints = self._normalize_int_uids(takeoff_uids, "takeoff")
        except ValueError as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.warning(
                "Invalid takeoff uids passed to %s: %s", label, takeoff_uids
            )
            return False
        if not uid_ints:
            return True
        try:
            self._run_selected_takeoffs_value_update(
                db_path,
                uid_ints,
                column,
                value,
                ACCESS_BULK_CHUNK_SIZE,
            )
            return True
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            if self._is_access_resource_exceeded(exc):
                self.logger.warning(
                    "Access resource limit while saving %s for %d takeoffs "
                    "with chunk size %d; retrying row-by-row in a fresh transaction.",
                    label,
                    len(uid_ints),
                    ACCESS_BULK_CHUNK_SIZE,
                )
                try:
                    self._run_selected_takeoffs_value_update(
                        db_path,
                        uid_ints,
                        column,
                        value,
                        1,
                    )
                    return True
                except Exception as retry_exc:
                    if self._record_caught_mutation_error(retry_exc):
                        raise
                    self.logger.exception(
                        "Failed to save %s row-by-row in %s", label, db_path
                    )
                    return False
            self.logger.exception("Failed to save %s in %s", label, db_path)
            return False

    def _run_selected_takeoffs_value_update(
        self,
        db_path: str,
        uid_ints: list[int],
        column: str,
        value,
        chunk_size: int,
    ) -> None:
        with self._connection(db_path) as conn:
            schema = self._schema(conn)
            self._require_write_columns(schema, "BidTakeoffs", ("UID", column))
            cursor = conn.cursor()
            self._execute_uid_in_update_chunks(
                cursor,
                "BidTakeoffs",
                "UID",
                {column: value},
                uid_ints,
                chunk_size,
            )

    def set_takeoffs_negative(
        self, db_path: str, takeoff_uids: List[str], is_negative: bool
    ) -> bool:
        return self._update_selected_takeoffs_value(
            db_path,
            takeoff_uids,
            "IsNegativeQuantity",
            is_negative,
            "takeoffs negative flag",
        )

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
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
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
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
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
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception(
                "Failed to bulk save takeoff rotations in %s", db_path
            )
            return False

    def save_takeoff_text_properties(self, db_path: str, updates: List[tuple]) -> bool:
        if not updates:
            return True
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                cursor = conn.cursor()
                for takeoff_uid, properties in updates:
                    values = {
                        self._TAKEOFF_TEXT_PROPERTY_COLUMNS[key]: value
                        for key, value in properties.items()
                        if key in self._TAKEOFF_TEXT_PROPERTY_COLUMNS
                    }
                    if not values:
                        continue
                    self._execute_update_values(
                        cursor,
                        schema,
                        "BidTakeoffs",
                        values,
                        ("UID",),
                        "[UID]=?",
                        [int(takeoff_uid)],
                        "save_takeoff_text_properties",
                    )
                return True
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception(
                "Failed to bulk save takeoff text properties in %s", db_path
            )
            return False

    def delete_takeoffs(self, db_path: str, takeoff_uids: List[str]) -> bool:
        try:
            uids = self._normalize_int_uids(takeoff_uids, "takeoff")
        except ValueError as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.warning(
                "Invalid takeoff uids passed to delete_takeoffs: %s", takeoff_uids
            )
            return False
        if not uids:
            return True
        try:
            self._run_delete_takeoffs(db_path, uids, ACCESS_BULK_CHUNK_SIZE)
            return True
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            if self._is_access_resource_exceeded(exc):
                self.logger.warning(
                    "Access resource limit while deleting %d takeoffs with chunk "
                    "size %d; retrying row-by-row in a fresh transaction.",
                    len(uids),
                    ACCESS_BULK_CHUNK_SIZE,
                )
                try:
                    self._run_delete_takeoffs(db_path, uids, 1)
                    return True
                except Exception as retry_exc:
                    if self._record_caught_mutation_error(retry_exc):
                        raise
                    self.logger.exception(
                        "Failed to delete takeoffs row-by-row in %s", db_path
                    )
                    return False
            self.logger.exception("Failed to delete takeoffs in %s", db_path)
            return False

    def _run_delete_takeoffs(
        self, db_path: str, uids: list[int], chunk_size: int
    ) -> None:
        with self._connection(db_path) as conn:
            schema = self._schema(conn)
            self._require_write_columns(schema, "BidTakeoffs", ("UID",))
            cursor = conn.cursor()
            for child in TAKEOFF_REFERENCE_TABLES:
                if schema.optional_table_missing(child):
                    continue
                for reference_column in (
                    "BidTakeoffFromUID",
                    "BidTakeoffToUID",
                ):
                    if not schema.column_exists(child, reference_column):
                        continue
                    self._execute_uid_in_delete_chunks(
                        cursor,
                        child,
                        reference_column,
                        uids,
                        chunk_size,
                    )
            if not schema.optional_table_missing(
                "BidPercents"
            ) and schema.column_exists("BidPercents", "BidTakeoffUID"):
                self._execute_uid_in_delete_chunks(
                    cursor,
                    "BidPercents",
                    "BidTakeoffUID",
                    uids,
                    chunk_size,
                )
            if schema.column_exists("BidTakeoffs", "ParentUID"):
                self._execute_uid_in_update_chunks(
                    cursor,
                    "BidTakeoffs",
                    "ParentUID",
                    {"ParentUID": None},
                    uids,
                    chunk_size,
                )
            self._execute_uid_in_delete_chunks(
                cursor,
                "BidTakeoffs",
                "UID",
                uids,
                chunk_size,
            )

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
                        if is_unassigned_area_uid(spec.area_uid)
                        else int(spec.area_uid)
                    )
                    parent_val = (
                        int(spec.parent_uid)
                        if spec.parent_uid and spec.parent_uid not in ("0", "")
                        else 0
                    )
                    new_uid = self._next_uid(cursor, "BidTakeoffs")
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
        except Exception as exc:
            if self._record_caught_mutation_error(exc):
                raise
            self.logger.exception("Failed to bulk insert takeoffs in %s", db_path)
            return []
