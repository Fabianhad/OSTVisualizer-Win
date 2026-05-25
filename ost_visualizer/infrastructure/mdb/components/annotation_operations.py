from types import MappingProxyType
from typing import Dict, List, Optional, Tuple
from ....application.dtos.insert_annotation_spec_dto import InsertAnnotationSpec
from ....application.dtos.paste_ref_remap_dto import PasteRefRemap
from .constants import encode_position, hex_to_color_int


class AnnotationOperationsMixin:
    _TEXT_PROPERTY_COLUMNS = (
        "UID",
        "Name",
        "FontName",
        "FontColor",
        "FontSize",
        "FontBold",
        "FontItalic",
        "FontUnderline",
        "TextAlign",
    )
    _DIMENSION_TEXT_PROPERTY_COLUMNS = (
        "UID",
        "FontName",
        "FontColor",
        "FontSize",
        "FontBold",
        "FontItalic",
        "FontUnderline",
    )
    _ANNOTATION_TABLE = MappingProxyType(
        {
            "line": "BidALines",
            "arrow": "BidArrows",
            "dimension": "BidDimensions",
            "cloud": "BidAnnotationClouds",
            "polygon": "BidAnnotationPolygons",
            "rect": "BidAnnotationRects",
            "oval": "BidAnnotationOvals",
            "ink": "BidAnnoInk",
            "text": "BidTexts",
            "highlight": "BidHighlights",
            "namedview": "BidNamedViews",
            "hotlink": "BidHotLinks",
            "callout": "BidCallOuts",
        }
    )

    def save_annotation_positions(
        self, db_path: str, positions: List[Tuple[str, str, List[float]]]
    ) -> bool:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                cursor = conn.cursor()
                for uid, annotation_type, position in positions:
                    table = self._ANNOTATION_TABLE.get(annotation_type)
                    if not table:
                        continue
                    if schema.optional_table_missing(table):
                        continue
                    self._require_write_columns(schema, table, ("UID", "Position"))
                    position_bytes = encode_position(position)
                    position_val = (
                        position_bytes.decode("latin-1")
                        if annotation_type in ("text", "callout")
                        else position_bytes
                    )
                    cursor.execute(
                        f"UPDATE [{table}] SET [Position]=? WHERE [UID]=?",
                        position_val,
                        int(uid),
                    )
                return True
        except Exception:
            self.logger.exception(
                "Failed to bulk save annotation positions in %s", db_path
            )
            return False

    def save_annotation_text_properties(
        self, db_path: str, updates: List[Tuple[str, str, Dict[str, object]]]
    ) -> bool:
        if not updates:
            return True
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                cursor = conn.cursor()
                for uid, annotation_type, properties in updates:
                    if annotation_type == "namedview":
                        table = self._ANNOTATION_TABLE[annotation_type]
                        if schema.optional_table_missing(table):
                            continue
                        self._require_write_columns(schema, table, ("UID", "Name"))
                        cursor.execute(
                            f"UPDATE [{table}] SET [Name]=? WHERE [UID]=?",
                            self._named_view_name_value(properties),
                            int(uid),
                        )
                        continue
                    if annotation_type == "dimension":
                        table = self._ANNOTATION_TABLE[annotation_type]
                        if schema.optional_table_missing(table):
                            continue
                        self._require_write_columns(
                            schema, table, self._DIMENSION_TEXT_PROPERTY_COLUMNS
                        )
                        values = self._dimension_text_property_update_values(
                            uid, properties
                        )
                        cursor.execute(
                            f"""
                            UPDATE [{table}]
                               SET [FontName]=?,
                                   [FontColor]=?,
                                   [FontSize]=?,
                                   [FontBold]=?,
                                   [FontItalic]=?,
                                   [FontUnderline]=?
                             WHERE [UID]=?
                            """,
                            *values,
                        )
                        continue
                    if annotation_type not in ("text", "callout"):
                        continue
                    table = self._ANNOTATION_TABLE[annotation_type]
                    if schema.optional_table_missing(table):
                        continue
                    self._require_write_columns(
                        schema, table, self._TEXT_PROPERTY_COLUMNS
                    )
                    values = self._text_property_update_values(uid, properties)
                    cursor.execute(
                        f"""
                        UPDATE [{table}]
                           SET [Name]=?,
                               [FontName]=?,
                               [FontColor]=?,
                               [FontSize]=?,
                               [FontBold]=?,
                               [FontItalic]=?,
                               [FontUnderline]=?,
                               [TextAlign]=?
                         WHERE [UID]=?
                        """,
                        *values,
                    )
                return True
        except Exception:
            self.logger.exception(
                "Failed to bulk save annotation text properties in %s", db_path
            )
            return False

    @staticmethod
    def _text_annotation_name_value(properties: Dict[str, object]):
        text_content = properties.get("Text", "")
        if isinstance(text_content, str):
            return text_content.encode("latin-1", errors="replace")
        return text_content

    @staticmethod
    def _named_view_name_value(properties: Dict[str, object]) -> str:
        return str(properties.get("Text", "") or "")

    def _text_property_update_values(
        self, uid: str, properties: Dict[str, object]
    ) -> Tuple[object, str, int, int, bool, bool, bool, int, int]:
        font_values = self._font_property_update_values(properties, 12)
        return (
            self._text_annotation_name_value(properties),
            *font_values,
            int(properties.get("TextAlign", 0) or 0),
            int(uid),
        )

    def _dimension_text_property_update_values(
        self, uid: str, properties: Dict[str, object]
    ) -> Tuple[str, int, int, bool, bool, bool, int]:
        font_values = self._font_property_update_values(properties, 10)
        return (*font_values, int(uid))

    def _font_property_update_values(
        self, properties: Dict[str, object], default_size: int
    ) -> Tuple[str, int, int, bool, bool, bool]:
        return (
            str(properties.get("FontName", "Arial") or "Arial"),
            self._text_property_color_int(properties),
            int(properties.get("FontSize", default_size) or default_size),
            bool(properties.get("FontBold", False)),
            bool(properties.get("FontItalic", False)),
            bool(properties.get("FontUnderline", False)),
        )

    def _text_property_color_int(self, properties: Dict[str, object]) -> int:
        color = properties.get("FontColor", 0)
        if isinstance(color, str):
            return hex_to_color_int(color)
        return int(color or 0)

    def insert_annotations(
        self,
        db_path: str,
        bid_uid: str,
        specs: List[InsertAnnotationSpec],
        ref_remap: Optional[PasteRefRemap] = None,
    ) -> List[str]:
        if not specs:
            return []
        new_uids = []
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                cursor = conn.cursor()
                for spec in specs:
                    page_uid = spec.page_uid
                    annotation_type = spec.annotation_type
                    position = spec.position
                    color = spec.color
                    width = spec.width
                    properties = spec.properties
                    layer_uid = spec.layer_uid
                    table = self._ANNOTATION_TABLE.get(annotation_type)
                    if not table:
                        new_uids.append(None)
                        continue
                    position_bytes = encode_position(position)
                    position_val = (
                        position_bytes.decode("latin-1")
                        if annotation_type in ("text", "callout")
                        else position_bytes
                    )
                    color_int = hex_to_color_int(color)
                    width_int = int(width) if width else 0
                    layer_int = int(layer_uid) if layer_uid else None
                    try:
                        cursor.execute(f"SELECT MAX([UID]) FROM [{table}]")
                        row = cursor.fetchone()
                        new_uid = (int(row[0]) + 1) if row and row[0] is not None else 1
                        self._execute_annotation_insert(
                            cursor,
                            schema,
                            table,
                            annotation_type,
                            new_uid,
                            int(bid_uid),
                            int(page_uid),
                            layer_int,
                            position_val,
                            color_int,
                            width_int,
                            properties,
                            ref_remap=ref_remap,
                        )
                        new_uids.append(str(new_uid))
                    except Exception:
                        self.logger.exception(
                            "Failed to insert %s annotation in %s",
                            annotation_type,
                            db_path,
                        )
                        new_uids.append(None)
        except Exception:
            self.logger.exception("Failed to bulk insert annotations in %s", db_path)
            return []
        return [u for u in new_uids if u is not None]

    def _execute_annotation_insert(
        self,
        cursor,
        schema,
        table,
        annotation_type,
        uid,
        bid_uid,
        page_uid,
        layer_int,
        position_val,
        color_int,
        width_int,
        properties,
        ref_remap: Optional[PasteRefRemap] = None,
    ):
        takeoff_remap = ref_remap.takeoff_uids if ref_remap else {}
        namedview_remap = ref_remap.namedview_uids if ref_remap else {}
        if annotation_type in ("line", "arrow"):
            from_uid_raw = properties.get("BidTakeoffFromUID")
            to_uid_raw = properties.get("BidTakeoffToUID")
            from_val = self._resolve_takeoff_fk(from_uid_raw, takeoff_remap)
            to_val = self._resolve_takeoff_fk(to_uid_raw, takeoff_remap)
            self._execute_insert_values(
                cursor,
                schema,
                table,
                {
                    "UID": uid,
                    "BidUID": bid_uid,
                    "BidPageUID": page_uid,
                    "BidTakeoffFromUID": from_val,
                    "BidTakeoffToUID": to_val,
                    "Position": position_val,
                    "Color": color_int,
                    "Width": width_int,
                },
                ("UID", "BidUID", "BidPageUID", "Position"),
                f"insert_{annotation_type}_annotation",
            )
        elif annotation_type == "dimension":
            from_uid_raw = properties.get("BidTakeoffFromUID")
            to_uid_raw = properties.get("BidTakeoffToUID")
            from_val = self._resolve_takeoff_fk(from_uid_raw, takeoff_remap)
            to_val = self._resolve_takeoff_fk(to_uid_raw, takeoff_remap)
            font_color = properties.get("FontColor", color_int)
            if isinstance(font_color, str):
                font_color = hex_to_color_int(font_color)
            self._execute_insert_values(
                cursor,
                schema,
                table,
                {
                    "UID": uid,
                    "BidUID": bid_uid,
                    "BidPageUID": page_uid,
                    "BidTakeoffFromUID": from_val,
                    "BidTakeoffToUID": to_val,
                    "Position": position_val,
                    "FontName": properties.get("FontName", "Arial"),
                    "FontColor": int(font_color or 0),
                    "FontSize": properties.get("FontSize", 10),
                    "FontBold": properties.get("FontBold", False),
                    "FontItalic": properties.get("FontItalic", False),
                    "FontUnderline": properties.get("FontUnderline", False),
                },
                ("UID", "BidUID", "BidPageUID", "Position"),
                "insert_dimension_annotation",
            )
        elif annotation_type == "text":
            text_content = properties.get("Text", "")
            if isinstance(text_content, str):
                text_content = text_content.encode("latin-1", errors="replace")
            self._execute_insert_values(
                cursor,
                schema,
                table,
                {
                    "UID": uid,
                    "BidUID": bid_uid,
                    "BidPageUID": page_uid,
                    "BidLayerUID": layer_int,
                    "Name": text_content,
                    "FontName": properties.get("FontName", "Arial"),
                    "FontColor": properties.get("FontColor", 0),
                    "FontSize": properties.get("FontSize", 12),
                    "FontBold": properties.get("FontBold", False),
                    "FontItalic": properties.get("FontItalic", False),
                    "FontUnderline": properties.get("FontUnderline", False),
                    "TextAlign": properties.get("TextAlign", 0),
                    "Position": position_val,
                },
                ("UID", "BidUID", "BidPageUID", "Position"),
                "insert_text_annotation",
            )
        elif annotation_type == "callout":
            text_content = properties.get("Text", "")
            if isinstance(text_content, str):
                text_content = text_content.encode("latin-1", errors="replace")
            self._execute_insert_values(
                cursor,
                schema,
                table,
                {
                    "UID": uid,
                    "BidUID": bid_uid,
                    "BidPageUID": page_uid,
                    "BidLayerUID": layer_int,
                    "Name": text_content,
                    "FontName": properties.get("FontName", "Arial"),
                    "FontColor": properties.get("FontColor", 0),
                    "FontSize": properties.get("FontSize", 12),
                    "FontBold": properties.get("FontBold", False),
                    "FontItalic": properties.get("FontItalic", False),
                    "FontUnderline": properties.get("FontUnderline", False),
                    "TextAlign": properties.get("TextAlign", 0),
                    "Position": position_val,
                    "Color": color_int,
                    "Width": width_int,
                },
                ("UID", "BidUID", "BidPageUID", "Position"),
                "insert_callout_annotation",
            )
        elif annotation_type == "highlight":
            self._execute_insert_values(
                cursor,
                schema,
                table,
                {
                    "UID": uid,
                    "BidUID": bid_uid,
                    "BidPageUID": page_uid,
                    "BidLayerUID": layer_int,
                    "Position": position_val,
                    "Color": color_int,
                },
                ("UID", "BidUID", "BidPageUID", "Position"),
                "insert_highlight_annotation",
            )
        elif annotation_type == "hotlink":
            page_view_uid = properties.get("BidPageViewUID")
            if page_view_uid not in (None, "", "0"):
                remapped = namedview_remap.get(str(page_view_uid))
                page_view_val = int(remapped if remapped is not None else page_view_uid)
            else:
                page_view_val = None
            self._execute_insert_values(
                cursor,
                schema,
                table,
                {
                    "UID": uid,
                    "BidUID": bid_uid,
                    "BidPageUID": page_uid,
                    "BidPageViewUID": page_view_val,
                    "BidLayerUID": layer_int,
                    "Position": position_val,
                    "Color": color_int,
                },
                ("UID", "BidUID", "BidPageUID", "Position"),
                "insert_hotlink_annotation",
            )
        elif annotation_type == "namedview":
            self._execute_insert_values(
                cursor,
                schema,
                table,
                {
                    "UID": uid,
                    "BidUID": bid_uid,
                    "BidPageUID": page_uid,
                    "Position": position_val,
                    "Color": color_int,
                },
                ("UID", "BidUID", "BidPageUID", "Position"),
                "insert_namedview_annotation",
            )
        elif annotation_type == "ink":
            self._execute_insert_values(
                cursor,
                schema,
                table,
                {
                    "UID": uid,
                    "BidUID": bid_uid,
                    "BidPageUID": page_uid,
                    "Position": position_val,
                    "Color": color_int,
                    "Width": width_int,
                },
                ("UID", "BidUID", "BidPageUID", "Position"),
                "insert_ink_annotation",
            )
        else:
            self._execute_insert_values(
                cursor,
                schema,
                table,
                {
                    "UID": uid,
                    "BidUID": bid_uid,
                    "BidPageUID": page_uid,
                    "BidLayerUID": layer_int,
                    "Position": position_val,
                    "Color": color_int,
                    "Width": width_int,
                },
                ("UID", "BidUID", "BidPageUID", "Position"),
                f"insert_{annotation_type}_annotation",
            )

    @staticmethod
    def _resolve_takeoff_fk(raw_uid, takeoff_remap: Dict[str, str]):
        if raw_uid in (None, "", "0", 0):
            return None
        remapped = takeoff_remap.get(str(raw_uid))
        if remapped is not None:
            return int(remapped)
        return None

    def delete_annotations(
        self, db_path: str, annotations: List[Tuple[str, str]]
    ) -> bool:
        if not annotations:
            return True
        by_table: dict = {}
        for uid, annotation_type in annotations:
            table = self._ANNOTATION_TABLE.get(annotation_type)
            if table:
                by_table.setdefault(table, []).append(int(uid))
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                cursor = conn.cursor()
                for table, uids in by_table.items():
                    if schema.optional_table_missing(table):
                        continue
                    self._require_write_columns(schema, table, ("UID",))
                    for uid in uids:
                        cursor.execute(f"DELETE FROM [{table}] WHERE [UID]=?", uid)
                return True
        except Exception:
            self.logger.exception("Failed to bulk delete annotations in %s", db_path)
            return False
