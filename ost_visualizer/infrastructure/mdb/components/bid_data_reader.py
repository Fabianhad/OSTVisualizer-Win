from typing import Any, Dict, List, Optional, Tuple
import pyodbc
from ....domain.dtos.raw_bid_data_dto import RawBidData
from ....domain.entities.area import BidArea
from ....domain.entities.cdn_type import CdnType
from ....domain.entities.condition import Condition
from ....domain.entities.condition_folder import BidConditionFolder
from ....domain.entities.layer import (
    BidLayer,
    BidLayers,
    IMAGE_LAYER_NAME,
    Layer,
    get_layer_uid_by_name,
    is_layer_visible,
)
from ....domain.entities.page_info import BidPageInfo
from ....domain.entities.takeoff import Takeoff
from ...parsers.ost_serializer import serialize_row
from ...parsers.position_parser import extract_z_value_from_name, parse_position
from ...parsers.utils.parser import decode_value, parse_float, parse_overlay_rect
from ..schema_contract import PAGE_SECTIONS, RAW_BID_TABLES, RAW_GLOBAL_TABLES
from .constants import PAGE_CONTENT_TABLES
from ..schema_compatibility import MdbSchemaInspector

BidConditions = Dict[str, Condition]
BidTakeoffs = List[Takeoff]
BidAreas = Dict[str, BidArea]
BidPages = Dict[str, BidPageInfo]
BidPageAreaSelections = Dict[str, Optional[str]]
CdnTypes = Dict[str, CdnType]
BidConditionFolders = Dict[str, BidConditionFolder]


class BidDataReaderMixin:
    def get_bid_data(self, file_path: str, bid_uid: str) -> Tuple[
        BidConditions,
        BidTakeoffs,
        BidAreas,
        BidPages,
        BidPageAreaSelections,
        CdnTypes,
        list,
        BidConditionFolders,
        Optional[str],
        Dict[str, Dict[str, Any]],
    ]:
        with self._connection(file_path) as connection:
            schema = MdbSchemaInspector(connection, self.logger)
            schema.require_column("BidPages", "UID")
            schema.require_column("BidPages", "BidUID")
            schema.require_column("BidTakeoffs", "UID")
            schema.require_column("BidTakeoffs", "BidUID")
            schema.require_column("BidTakeoffs", "BidConditionUID")
            schema.require_column("BidTakeoffs", "BidPageUID")
            schema.require_column("BidTakeoffs", "Position")
            schema.require_column("BidConditions", "UID")
            schema.require_column("BidConditions", "BidUID")
            schema.require_column("BidConditions", "Name")
            schema.require_column("BidConditions", "Type")
            cdn_types = self._parse_cdn_types(connection)
            bid_layers = self._parse_bid_layers_for_bid(connection, bid_uid)
            bid_pages = self._parse_bid_pages_for_bid(
                connection, bid_uid, bid_layers, schema
            )
            bid_areas = self._parse_bid_areas_for_bid(connection, bid_uid, schema)
            page_area_selections = self._parse_page_area_selections_for_bid(
                connection, bid_pages, schema
            )
            bid_conditions = self._parse_bid_conditions_for_bid(
                connection, bid_uid, bid_layers, cdn_types, schema
            )
            bid_takeoffs, takeoff_extras = self._parse_bid_takeoffs_for_bid(
                connection, bid_uid, schema
            )
            bid_annotations = self._parse_bid_annotations_for_bid(
                connection, bid_uid, bid_layers, schema
            )
            bid_condition_folders = self._parse_bid_condition_folders_for_bid(
                connection, bid_uid, schema
            )
            selected_page_uid = self._parse_bid_selected_page(connection, bid_uid)
            return (
                bid_conditions,
                bid_takeoffs,
                bid_areas,
                bid_pages,
                page_area_selections,
                cdn_types,
                bid_annotations,
                bid_condition_folders,
                selected_page_uid,
                takeoff_extras,
            )

    def _parse_bid_selected_page(self, connection, bid_uid: str) -> Optional[str]:
        schema = MdbSchemaInspector(connection, self.logger)
        if schema.optional_table_missing("BidSettings"):
            return None
        schema.require_column("BidSettings", "BidUID")
        if not schema.column_exists("BidSettings", "BidPageSelectedUID"):
            schema.optional_column("BidSettings", "BidPageSelectedUID", "NULL")
            return None
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT [BidPageSelectedUID] FROM [BidSettings] WHERE [BidUID]=?",
                    bid_uid,
                )
                row = cursor.fetchone()
                if row and row[0]:
                    return str(row[0])
        except pyodbc.Error:
            pass
        return None

    def _parse_bid_areas_for_bid(
        self,
        connection: "pyodbc.Connection",
        bid_uid: str,
        schema: MdbSchemaInspector,
    ) -> BidAreas:
        areas: BidAreas = {}
        if schema.optional_table_missing("BidAreas"):
            return areas
        schema.require_column("BidAreas", "UID")
        schema.require_column("BidAreas", "BidUID")
        parent_col = schema.optional_column("BidAreas", "ParentUID", "NULL")
        name_col = schema.optional_column("BidAreas", "Name", "NULL")
        sequence_col = schema.optional_column("BidAreas", "Sequence", "0")
        guid_col = schema.optional_column("BidAreas", "GUID", "NULL")
        order_clause = schema.order_by_existing("BidAreas", ("Sequence",), "[UID]")
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT [UID], [BidUID], "
                    f"{parent_col}, {name_col}, {sequence_col}, {guid_col} "
                    f"FROM [BidAreas] WHERE [BidUID] = ? ORDER BY {order_clause}",
                    bid_uid,
                )
                for row in cursor.fetchall():
                    uid = str(row[0])
                    areas[uid] = BidArea(
                        uid=uid,
                        bid_uid=str(row[1]),
                        parent_uid=str(row[2]) if row[2] is not None else "",
                        name=decode_value(row[3]) if row[3] else "",
                        sequence=int(row[4]) if row[4] is not None else 0,
                        guid=str(row[5]) if row[5] else "",
                    )
        except pyodbc.Error:
            pass
        return areas

    def get_database_statistics(self, file_path: str) -> Dict[str, int]:
        with self._connection(file_path) as connection:
            schema = MdbSchemaInspector(connection, self.logger)
            with connection.cursor() as cursor:
                project_count = self._count_table(cursor, schema, "BidProjects")
                bid_count = self._count_table(cursor, schema, "Bids")
                takeoff_count = self._count_table(cursor, schema, "BidTakeoffs")
                condition_count = self._count_table(cursor, schema, "BidConditions")
                page_count = self._count_table(cursor, schema, "BidPages")
                return {
                    "projects": project_count,
                    "bids": bid_count,
                    "takeoffs": takeoff_count,
                    "conditions": condition_count,
                    "pages": page_count,
                }

    def _count_table(
        self, cursor: "pyodbc.Cursor", schema: MdbSchemaInspector, table: str
    ) -> int:
        if schema.optional_table_missing(table):
            return 0
        cursor.execute(f"SELECT COUNT(*) FROM [{table}]")
        return int(cursor.fetchone()[0])

    def get_raw_bid_data(self, file_path: str, bid_uid: str) -> RawBidData:
        with self._connection(file_path) as connection:
            result = RawBidData()
            result.bid_row = self._select_all_single(connection, "Bids", "UID", bid_uid)
            bid_tables_with_totals = list(RAW_BID_TABLES) + ["BidTakeoffTotals"]
            for table in bid_tables_with_totals:
                result.bid_tables[table] = self._select_all_filtered(
                    connection, table, "BidUID", bid_uid
                )
            page_uids = [row["UID"] for row in result.bid_tables.get("BidPages", [])]
            for table in PAGE_SECTIONS:
                result.page_tables[table] = self._select_all_by_bid_or_page(
                    connection, table, bid_uid, page_uids
                )
            for table in RAW_GLOBAL_TABLES:
                result.global_tables[table] = self._select_all_unfiltered(
                    connection, table
                )
            return result

    def _select_all_single(
        self,
        connection: "pyodbc.Connection",
        table: str,
        key_col: str,
        key_val: str,
    ) -> Dict[str, str]:
        schema = MdbSchemaInspector(connection, self.logger)
        if schema.optional_table_missing(table) or not schema.column_exists(
            table, key_col
        ):
            return {}
        select_clause = self._select_all_columns(schema, table)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {select_clause} FROM [{table}] WHERE [{key_col}] = ?",
                    key_val,
                )
                row = cursor.fetchone()
                if row:
                    return serialize_row(row, cursor.description)
        except pyodbc.Error:
            pass
        return {}

    def _select_all_filtered(
        self,
        connection: "pyodbc.Connection",
        table: str,
        key_col: str,
        key_val: str,
    ) -> List[Dict[str, str]]:
        rows_out: List[Dict[str, str]] = []
        schema = MdbSchemaInspector(connection, self.logger)
        if schema.optional_table_missing(table) or not schema.column_exists(
            table, key_col
        ):
            return rows_out
        select_clause = self._select_all_columns(schema, table)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {select_clause} FROM [{table}] WHERE [{key_col}] = ?",
                    key_val,
                )
                desc = cursor.description
                for row in cursor.fetchall():
                    rows_out.append(serialize_row(row, desc))
        except pyodbc.Error:
            pass
        return rows_out

    def _select_all_by_bid_or_page(
        self,
        connection: "pyodbc.Connection",
        table: str,
        bid_uid: str,
        page_uids: List[str],
    ) -> List[Dict[str, str]]:
        schema = MdbSchemaInspector(connection, self.logger)
        if schema.optional_table_missing(table):
            return []
        select_clause = self._select_all_columns(schema, table)
        try:
            with connection.cursor() as cursor:
                if not schema.column_exists(table, "BidUID"):
                    raise pyodbc.Error("BidUID column missing")
                cursor.execute(
                    f"SELECT {select_clause} FROM [{table}] WHERE [BidUID] = ?",
                    bid_uid,
                )
                desc = cursor.description
                return [serialize_row(row, desc) for row in cursor.fetchall()]
        except pyodbc.Error:
            pass
        if not page_uids:
            return []
        try:
            placeholders = ",".join(["?"] * len(page_uids))
            with connection.cursor() as cursor:
                if not schema.column_exists(table, "BidPageUID"):
                    return []
                cursor.execute(
                    f"SELECT {select_clause} FROM [{table}] "
                    f"WHERE [BidPageUID] IN ({placeholders})",
                    *page_uids,
                )
                desc = cursor.description
                return [serialize_row(row, desc) for row in cursor.fetchall()]
        except pyodbc.Error:
            pass
        return []

    def _select_all_unfiltered(
        self, connection: "pyodbc.Connection", table: str
    ) -> List[Dict[str, str]]:
        rows_out: List[Dict[str, str]] = []
        schema = MdbSchemaInspector(connection, self.logger)
        if schema.optional_table_missing(table):
            return rows_out
        select_clause = self._select_all_columns(schema, table)
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT {select_clause} FROM [{table}]")
                desc = cursor.description
                for row in cursor.fetchall():
                    rows_out.append(serialize_row(row, desc))
        except pyodbc.Error:
            pass
        return rows_out

    def _select_all_columns(self, schema: MdbSchemaInspector, table: str) -> str:
        columns = sorted(schema.get_columns(table))
        return ", ".join(f"[{column}]" for column in columns)

    def _parse_bid_layers_for_bid(
        self, connection: "pyodbc.Connection", bid_uid: str
    ) -> BidLayers:
        bid_layers: BidLayers = {}
        schema = MdbSchemaInspector(connection, self.logger)
        if schema.optional_table_missing("BidLayers"):
            return bid_layers
        schema.require_column("BidLayers", "UID")
        schema.require_column("BidLayers", "BidUID")
        schema.require_column("BidLayers", "Name")
        show_col = schema.optional_column("BidLayers", "Show", "-1")
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT [UID], [Name], {show_col}
                FROM [BidLayers]
                WHERE [BidUID] = ?
                """,
                bid_uid,
            )
            for row in cursor.fetchall():
                uid = str(row.UID)
                name = decode_value(row.Name) or ""
                bid_layers[uid] = Layer(
                    uid=uid,
                    name=name,
                    visible=row.Show in (1, -1),
                )
            return bid_layers

    def get_pages_with_takeoffs(self, file_path: str, bid_uid: str) -> set:
        result = set()
        try:
            with self._connection(file_path) as connection:
                schema = MdbSchemaInspector(connection, self.logger)
                if schema.optional_table_missing("BidTakeoffs"):
                    return result
                schema.require_column("BidTakeoffs", "BidUID")
                schema.require_column("BidTakeoffs", "BidPageUID")
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT DISTINCT [BidPageUID] FROM [BidTakeoffs] "
                        "WHERE [BidUID] = ?",
                        bid_uid,
                    )
                    for row in cursor.fetchall():
                        if row[0] is not None:
                            result.add(str(row[0]))
        except pyodbc.Error:
            pass
        return result

    def get_pages_with_delete_content(self, file_path: str, bid_uid: str) -> set:
        result = set()
        content_tables = PAGE_CONTENT_TABLES
        try:
            with self._connection(file_path) as connection:
                schema = MdbSchemaInspector(connection, self.logger)
                if schema.optional_table_missing("BidPages"):
                    return result
                schema.require_column("BidPages", "UID")
                schema.require_column("BidPages", "BidUID")
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT [UID] FROM [BidPages] WHERE [BidUID] = ?", bid_uid
                    )
                    bid_page_uids = {
                        str(row[0]) for row in cursor.fetchall() if row[0] is not None
                    }
                    if not bid_page_uids:
                        return result
                    for table in content_tables:
                        if schema.optional_table_missing(
                            table
                        ) or not schema.column_exists(table, "BidPageUID"):
                            continue
                        cursor.execute(
                            f"SELECT DISTINCT [BidPageUID] FROM [{table}] "
                            "WHERE [BidPageUID] IS NOT NULL"
                        )
                        for row in cursor.fetchall():
                            page_uid = str(row[0])
                            if page_uid in bid_page_uids:
                                result.add(page_uid)
        except Exception:
            self.logger.warning(
                "Failed to load pages with delete-sensitive content for bid %s",
                bid_uid,
                exc_info=True,
            )
        return result

    def get_bid_layers_for_sidebar(
        self, file_path: str, bid_uid: str
    ) -> List[BidLayer]:
        with self._connection(file_path) as connection:
            schema = MdbSchemaInspector(connection, self.logger)
            if schema.optional_table_missing("BidLayers"):
                return []
            schema.require_column("BidLayers", "UID")
            schema.require_column("BidLayers", "BidUID")
            schema.require_column("BidLayers", "Name")
            layer_select = ", ".join(
                [
                    "[UID]",
                    "[BidUID]",
                    schema.optional_column("BidLayers", "IsTemplate", "0"),
                    "[Name]",
                    schema.optional_column("BidLayers", "Show", "-1"),
                    schema.optional_column("BidLayers", "IsLocked", "0"),
                    schema.optional_column("BidLayers", "Sequence", "0"),
                ]
            )
            template_filter = ""
            if schema.column_exists("BidLayers", "IsTemplate") and schema.column_exists(
                "BidLayers", "IsLocked"
            ):
                template_filter = " OR ([IsTemplate] <> 0 AND [IsLocked] <> 0)"
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {layer_select}
                    FROM [BidLayers]
                    WHERE [BidUID] = ?{template_filter}
                    """,
                    bid_uid,
                )
                layers: List[BidLayer] = []
                for row in cursor.fetchall():
                    layers.append(self._bid_layer_from_row(row))
                return layers

    def get_default_layers(self, file_path: str) -> List[BidLayer]:
        with self._connection(file_path) as connection:
            schema = MdbSchemaInspector(connection, self.logger)
            if schema.optional_table_missing("BidLayers"):
                return []
            schema.require_column("BidLayers", "UID")
            schema.require_column("BidLayers", "Name")
            if not schema.column_exists("BidLayers", "IsTemplate"):
                return []
            layer_select = ", ".join(
                [
                    "[UID]",
                    schema.optional_column("BidLayers", "BidUID", "NULL"),
                    "[IsTemplate]",
                    "[Name]",
                    schema.optional_column("BidLayers", "Show", "-1"),
                    schema.optional_column("BidLayers", "IsLocked", "0"),
                    schema.optional_column("BidLayers", "Sequence", "0"),
                ]
            )
            order_expr = (
                "[Sequence]"
                if schema.column_exists("BidLayers", "Sequence")
                else "[UID]"
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {layer_select}
                    FROM [BidLayers]
                    WHERE [IsTemplate] <> 0
                    ORDER BY {order_expr}
                    """
                )
                return [self._bid_layer_from_row(row) for row in cursor.fetchall()]

    @staticmethod
    def _bid_layer_from_row(row) -> BidLayer:
        raw_bid_uid = row.BidUID
        layer_bid_uid = str(raw_bid_uid) if raw_bid_uid else ""
        return BidLayer(
            uid=str(row.UID),
            bid_uid=layer_bid_uid,
            name=decode_value(row.Name) or "",
            show=row.Show in (1, -1),
            sequence=int(row.Sequence) if row.Sequence is not None else 0,
            is_template=row.IsTemplate not in (0, None),
            is_locked=row.IsLocked not in (0, None),
        )

    def _parse_bid_pages_for_bid(
        self,
        connection: "pyodbc.Connection",
        bid_uid: str,
        bid_layers: BidLayers,
        schema: MdbSchemaInspector,
    ) -> BidPages:
        bid_pages: BidPages = {}
        image_layer_uid = get_layer_uid_by_name(bid_layers, IMAGE_LAYER_NAME)
        image_layer_visible = is_layer_visible(bid_layers, image_layer_uid)
        page_select = ", ".join(
            [
                "[UID]",
                schema.optional_column("BidPages", "Name", "NULL"),
                schema.optional_column("BidPages", "SheetNo", "NULL"),
                schema.optional_column("BidPages", "Sequence", "0"),
                schema.optional_column("BidPages", "ImagePath", "NULL"),
                schema.optional_column("BidPages", "Width", "0"),
                schema.optional_column("BidPages", "Height", "0"),
                schema.optional_column("BidPages", "ScaleFactor1", "1"),
                schema.optional_column("BidPages", "ScaleFactor2", "1"),
                schema.optional_column("BidPages", "Rotation", "0"),
                schema.optional_column("BidPages", "FlipX", "0"),
                schema.optional_column("BidPages", "FlipY", "0"),
                schema.optional_column("BidPages", "Index1", "1"),
                schema.optional_column("BidPages", "Show", "0"),
                schema.optional_column("BidPages", "OverlayImagePath", "NULL"),
                schema.optional_column("BidPages", "OverlayOffsetX", "0"),
                schema.optional_column("BidPages", "OverlayOffsetY", "0"),
                schema.optional_column("BidPages", "OverlayRotation", "0"),
                schema.optional_column("BidPages", "OverlayRect", "NULL"),
                schema.optional_column("BidPages", "OverlayResized", "0"),
                schema.optional_column("BidPages", "DeskewRotationOverlay", "0"),
                schema.optional_column("BidPages", "ZoomFac", "0"),
                schema.optional_column("BidPages", "CurrentX", "0"),
                schema.optional_column("BidPages", "CurrentY", "0"),
                schema.optional_column("BidPages", "Invert", "0"),
                schema.optional_column("BidPages", "Bitonal", "0"),
            ]
        )
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {page_select}
                FROM [BidPages]
                WHERE [BidUID] = ?
                """,
                bid_uid,
            )
            for row in cursor.fetchall():
                uid = str(row.UID)
                name_str = decode_value(row.Name)
                overlay_rect_str = decode_value(row.OverlayRect)
                overlay_rect = (0.0, 0.0, 0.0, 0.0)
                if overlay_rect_str:
                    rect_x, rect_y, rect_w, rect_h = parse_overlay_rect(
                        overlay_rect_str
                    )
                    overlay_rect = (rect_x, rect_y, rect_w, rect_h)
                bid_pages[uid] = BidPageInfo(
                    name=name_str,
                    sheet_no=decode_value(row.SheetNo),
                    sequence=int(row.Sequence or 0),
                    image_path=decode_value(row.ImagePath) or None,
                    width_pts=parse_float(row.Width) * 72.0,
                    height_pts=parse_float(row.Height) * 72.0,
                    scale_factor1=parse_float(row.ScaleFactor1, 1.0),
                    scale_factor2=parse_float(row.ScaleFactor2, 1.0),
                    rotation=int(row.Rotation or 0) % 360,
                    flip_x=row.FlipX in (-1, True),
                    flip_y=row.FlipY in (-1, True),
                    page_index=max(0, int(row.Index1 or 1) - 1),
                    layer_visible=image_layer_visible,
                    overlay_image_path=decode_value(row.OverlayImagePath) or None,
                    overlay_offset_x=parse_float(row.OverlayOffsetX, 0.0),
                    overlay_offset_y=parse_float(row.OverlayOffsetY, 0.0),
                    overlay_rotation=parse_float(row.OverlayRotation, 0.0),
                    overlay_resized=row.OverlayResized in (-1, True),
                    deskew_rotation_overlay=parse_float(row.DeskewRotationOverlay, 0.0),
                    overlay_rect=overlay_rect,
                    image_show_mode=int(row.Show) if row.Show is not None else 0,
                    zoom_fac=parse_float(row.ZoomFac, 0.0),
                    current_x=parse_float(row.CurrentX, 0.0),
                    current_y=parse_float(row.CurrentY, 0.0),
                    invert=row.Invert in (-1, True),
                    bitonal=row.Bitonal in (-1, True),
                )
            return bid_pages

    def _parse_selected_area_for_page(
        self,
        connection: "pyodbc.Connection",
        page_uid: str,
        schema: MdbSchemaInspector,
    ) -> Optional[str]:
        if schema.optional_table_missing("BidPageSettings"):
            return None
        schema.require_column("BidPageSettings", "BidPageUID")
        schema.require_column("BidPageSettings", "BidAreaUID")
        schema.require_column("BidPageSettings", "BidAreaSelected")
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT BidAreaUID, BidAreaSelected
                FROM BidPageSettings
                WHERE BidPageUID = ? AND BidAreaSelected > 0
                ORDER BY BidAreaSelected DESC
                """,
                page_uid,
            )
            row = cursor.fetchone()
            if row:
                return str(row.BidAreaUID) if row.BidAreaUID is not None else "0"
            return None

    def _parse_page_area_selections_for_bid(
        self,
        connection: "pyodbc.Connection",
        bid_pages: BidPages,
        schema: MdbSchemaInspector,
    ) -> BidPageAreaSelections:
        page_area_selections: BidPageAreaSelections = {}
        for page_uid in bid_pages.keys():
            selected_area = self._parse_selected_area_for_page(
                connection, page_uid, schema
            )
            page_area_selections[page_uid] = selected_area
        return page_area_selections

    def _parse_bid_conditions_for_bid(
        self,
        connection: "pyodbc.Connection",
        bid_uid: str,
        bid_layers: BidLayers,
        cdn_types: CdnTypes,
        schema: MdbSchemaInspector,
    ) -> BidConditions:
        bid_conditions: BidConditions = {}
        condition_select = ", ".join(
            [
                "[UID]",
                "[Name]",
                "[Type]",
                schema.optional_column("BidConditions", "Thickness", "0"),
                schema.optional_column("BidConditions", "Height", "0"),
                schema.optional_column("BidConditions", "Width", "0"),
                schema.optional_column("BidConditions", "Depth", "0"),
                schema.optional_column("BidConditions", "Rise", "0"),
                schema.optional_column("BidConditions", "Run", "0"),
                schema.optional_column("BidConditions", "Shape", "0"),
                schema.optional_column("BidConditions", "ColorFill", "0"),
                schema.optional_column("BidConditions", "CdnTypeUID", "NULL"),
                schema.optional_column("BidConditions", "Pattern", "0"),
                schema.optional_column("BidConditions", "Spacing", "0"),
                schema.optional_column("BidConditions", "BidLayerUID", "NULL"),
                schema.optional_column("BidConditions", "UOM1", "0"),
                schema.optional_column("BidConditions", "UOM2", "0"),
                schema.optional_column("BidConditions", "UOM3", "0"),
                schema.optional_column("BidConditions", "Quantity1", "0"),
                schema.optional_column("BidConditions", "Quantity2", "0"),
                schema.optional_column("BidConditions", "Quantity3", "0"),
                schema.optional_column("BidConditions", "RefNo", "0"),
                schema.optional_column("BidConditions", "DisplaySize", "100"),
                schema.optional_column("BidConditions", "DropRun", "0"),
                schema.optional_column("BidConditions", "DropValue", "0"),
                schema.optional_column(
                    "BidConditions", "BidConditionFolderUID", "NULL"
                ),
                schema.optional_column("BidConditions", "Notes", "NULL"),
                schema.optional_column("BidConditions", "RoundQuantity", "0"),
                schema.optional_column("BidConditions", "RoundUp", "0"),
                schema.optional_column("BidConditions", "Trim", "0"),
                schema.optional_column("BidConditions", "IsCurvedSegment", "0"),
                schema.optional_column("BidConditions", "Grid", "0"),
                schema.optional_column("BidConditions", "GridSize1", "0"),
                schema.optional_column("BidConditions", "GridSize2", "0"),
                schema.optional_column("BidConditions", "Gap", "0"),
                schema.optional_column("BidConditions", "DisplayDimension", "0"),
                schema.optional_column("BidConditions", "DisplayName", "0"),
                schema.optional_column("BidConditions", "DisplayGridWhileDrawing", "0"),
            ]
        )
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {condition_select}
                FROM [BidConditions]
                WHERE [BidUID] = ?
                """,
                bid_uid,
            )
            for row in cursor.fetchall():
                uid = str(row.UID)
                name = decode_value(row.Name)
                condition_type = int(row.Type) if row.Type is not None else 0
                thickness = float(row.Thickness) if row.Thickness is not None else 0.0
                height = float(row.Height) if row.Height is not None else 0.0
                width = float(row.Width) if row.Width is not None else 0.0
                depth = float(row.Depth) if row.Depth is not None else 0.0
                rise = float(row.Rise) if row.Rise is not None else 0.0
                run = float(row.Run) if row.Run is not None else 0.0
                shape = int(row.Shape) if row.Shape is not None else 0
                color_fill = int(row.ColorFill) if row.ColorFill is not None else 0
                z_value, is_top = extract_z_value_from_name(name)
                pattern = int(row.Pattern) if row.Pattern is not None else 0
                spacing = float(row.Spacing) if row.Spacing is not None else 0.0
                cdn_type_uid = (
                    str(row.CdnTypeUID) if row.CdnTypeUID is not None else None
                )
                cdn_type_obj = cdn_types.get(cdn_type_uid) if cdn_type_uid else None
                cdn_type_name = cdn_type_obj.name if cdn_type_obj else "Unknown"
                uom1 = int(row.UOM1) if row.UOM1 is not None else 0
                uom2 = int(row.UOM2) if row.UOM2 is not None else 0
                uom3 = int(row.UOM3) if row.UOM3 is not None else 0
                qty1 = int(row.Quantity1) if row.Quantity1 is not None else 0
                qty2 = int(row.Quantity2) if row.Quantity2 is not None else 0
                qty3 = int(row.Quantity3) if row.Quantity3 is not None else 0
                ref_no = int(row.RefNo) if row.RefNo is not None else 0
                display_size = (
                    float(row.DisplaySize) if row.DisplaySize is not None else 100.0
                )
                drop_run = int(row.DropRun) if row.DropRun is not None else 0
                drop_value = float(row.DropValue) if row.DropValue is not None else 0.0
                bid_layer_uid = str(row.BidLayerUID)
                layer_visible = is_layer_visible(bid_layers, bid_layer_uid)
                folder_uid = (
                    str(row.BidConditionFolderUID)
                    if row.BidConditionFolderUID is not None
                    else None
                )
                notes_raw = row.Notes
                if isinstance(notes_raw, (bytes, bytearray)):
                    notes = notes_raw.decode("utf-8", errors="replace")
                else:
                    notes = decode_value(notes_raw) if notes_raw else ""
                round_quantity = (
                    bool(row.RoundQuantity) if row.RoundQuantity is not None else False
                )
                round_up = float(row.RoundUp) if row.RoundUp is not None else 0.0
                trim = bool(row.Trim) if row.Trim is not None else False
                is_curved_segment = (
                    bool(row.IsCurvedSegment)
                    if row.IsCurvedSegment is not None
                    else False
                )
                grid_flag = bool(row.Grid) if row.Grid is not None else False
                grid_size1 = float(row.GridSize1) if row.GridSize1 is not None else 0.0
                grid_size2 = float(row.GridSize2) if row.GridSize2 is not None else 0.0
                gap_val = float(row.Gap) if row.Gap is not None else 0.0
                display_dimension = (
                    bool(row.DisplayDimension)
                    if row.DisplayDimension is not None
                    else False
                )
                display_name_flag = (
                    bool(row.DisplayName) if row.DisplayName is not None else False
                )
                display_grid_while_drawing = (
                    bool(row.DisplayGridWhileDrawing)
                    if row.DisplayGridWhileDrawing is not None
                    else False
                )
                bid_conditions[uid] = Condition(
                    uid=uid,
                    name=name,
                    condition_type=condition_type,
                    thickness=thickness,
                    height=height,
                    width=width,
                    depth=depth,
                    rise=rise,
                    run=run,
                    shape=shape,
                    color_fill=color_fill,
                    z_value=z_value,
                    is_top=is_top,
                    cdn_type_uid=cdn_type_uid,
                    cdn_type_name=cdn_type_name,
                    folder_uid=folder_uid,
                    pattern=pattern,
                    spacing=spacing,
                    layer_visible=layer_visible,
                    uom1=uom1,
                    uom2=uom2,
                    uom3=uom3,
                    calc_type1=qty1,
                    calc_type2=qty2,
                    calc_type3=qty3,
                    ref_no=ref_no,
                    display_size=display_size,
                    drop_run=bool(drop_run),
                    drop_value=drop_value,
                    notes=notes,
                    layer_uid=bid_layer_uid,
                    round_quantity=round_quantity,
                    round_up=round_up,
                    trim=trim,
                    is_curved_segment=is_curved_segment,
                    grid=grid_flag,
                    grid_size1=grid_size1,
                    grid_size2=grid_size2,
                    gap=gap_val,
                    display_dimension=display_dimension,
                    display_name=display_name_flag,
                    display_grid_while_drawing=display_grid_while_drawing,
                )
            return bid_conditions

    def _parse_bid_condition_folders_for_bid(
        self,
        connection: "pyodbc.Connection",
        bid_uid: str,
        schema: MdbSchemaInspector,
    ) -> BidConditionFolders:
        folders: BidConditionFolders = {}
        if schema.optional_table_missing("BidConditionFolders"):
            return folders
        schema.require_column("BidConditionFolders", "UID")
        schema.require_column("BidConditionFolders", "BidUID")
        schema.require_column("BidConditionFolders", "Name")
        parent_uid_col = schema.optional_column(
            "BidConditionFolders", "ParentUID", "NULL"
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT [UID], [Name], {parent_uid_col} "
                    "FROM [BidConditionFolders] WHERE [BidUID] = ?",
                    bid_uid,
                )
                for row in cursor.fetchall():
                    uid = str(row.UID)
                    name = decode_value(row.Name)
                    parent_uid = (
                        str(row.ParentUID) if row.ParentUID is not None else None
                    )
                    folders[uid] = BidConditionFolder(
                        uid=uid,
                        name=name,
                        bid_uid=bid_uid,
                        parent_uid=parent_uid,
                    )
        except pyodbc.Error:
            pass
        return folders

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

    def _parse_bid_takeoffs_for_bid(
        self,
        connection: "pyodbc.Connection",
        bid_uid: str,
        schema: MdbSchemaInspector,
    ) -> Tuple[BidTakeoffs, Dict[str, Dict[str, Any]]]:
        bid_takeoffs: BidTakeoffs = []
        takeoff_extras: Dict[str, Dict[str, Any]] = {}
        try:
            with connection.cursor() as cursor:
                takeoff_columns = schema.get_columns("BidTakeoffs")
                for optional_column, default_sql in (
                    ("BidAreaUID", "0"),
                    ("Rotation", "0"),
                    ("Curve", "-1"),
                    ("ParentUID", "0"),
                    ("IsNegativeQuantity", "0"),
                ):
                    if optional_column not in takeoff_columns:
                        schema.optional_column(
                            "BidTakeoffs", optional_column, default_sql
                        )
                select_columns = [f"[{column}]" for column in sorted(takeoff_columns)]
                cursor.execute(
                    f"SELECT {', '.join(select_columns)} "
                    "FROM [BidTakeoffs] WHERE [BidUID] = ?",
                    bid_uid,
                )
                col_names = [d[0] for d in cursor.description]
                extra_cols = [
                    c for c in col_names if c not in self._TAKEOFF_TYPED_COLUMNS
                ]
                for row in cursor.fetchall():
                    row_data = dict(zip(col_names, row))
                    uid = str(row_data["UID"])
                    condition_uid = str(row_data["BidConditionUID"])
                    bid_page_uid = str(row_data["BidPageUID"])
                    bid_area_uid = str(row_data.get("BidAreaUID") or "0")
                    position_raw = row_data["Position"]
                    parent_uid = str(row_data.get("ParentUID") or "0")
                    rotation = (
                        float(row_data.get("Rotation"))
                        if row_data.get("Rotation") is not None
                        else 0.0
                    )
                    curve = (
                        int(row_data.get("Curve"))
                        if row_data.get("Curve") is not None
                        else -1
                    )
                    is_negative_quantity = bool(row_data.get("IsNegativeQuantity", 0))
                    dimension_font_name = (
                        str(row_data.get("FontName"))
                        if row_data.get("FontName")
                        else None
                    )
                    dimension_font_color = (
                        int(row_data["FontColor"])
                        if row_data.get("FontColor") is not None
                        else None
                    )
                    dimension_font_size = (
                        abs(int(row_data["FontSize"]))
                        if row_data.get("FontSize") not in (None, 0)
                        else None
                    )
                    name_font_name = (
                        str(row_data.get("NameFontName"))
                        if row_data.get("NameFontName")
                        else None
                    )
                    name_font_color = (
                        int(row_data["NameFontColor"])
                        if row_data.get("NameFontColor") is not None
                        else None
                    )
                    name_font_size = (
                        abs(int(row_data["NameFontSize"]))
                        if row_data.get("NameFontSize") not in (None, 0)
                        else None
                    )
                    if isinstance(position_raw, bytes):
                        position_str = position_raw.decode("latin-1")
                    else:
                        position_str = str(position_raw)
                    position = parse_position(position_str)
                    bid_takeoffs.append(
                        Takeoff(
                            uid=uid,
                            condition_uid=condition_uid,
                            page_uid=bid_page_uid,
                            area_uid=bid_area_uid,
                            position=position,
                            rotation=rotation,
                            curve=curve,
                            parent_uid=parent_uid,
                            is_negative=is_negative_quantity,
                            dimension_font_name=dimension_font_name,
                            dimension_font_color=dimension_font_color,
                            dimension_font_size=dimension_font_size,
                            dimension_font_bold=bool(row_data.get("FontBold", False)),
                            dimension_font_italic=bool(
                                row_data.get("FontItalic", False)
                            ),
                            dimension_font_underline=bool(
                                row_data.get("FontUnderline", False)
                            ),
                            name_font_name=name_font_name,
                            name_font_color=name_font_color,
                            name_font_size=name_font_size,
                            name_font_bold=bool(row_data.get("NameFontBold", False)),
                            name_font_italic=bool(
                                row_data.get("NameFontItalic", False)
                            ),
                            name_font_underline=bool(
                                row_data.get("NameFontUnderline", False)
                            ),
                        )
                    )
                    takeoff_extras[uid] = {c: row_data[c] for c in extra_cols}
        except pyodbc.Error as exc:
            if "HY109" not in str(exc) and "Record is deleted" not in str(exc):
                raise
        return bid_takeoffs, takeoff_extras
