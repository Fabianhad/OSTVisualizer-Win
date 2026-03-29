from typing import Any, List
import pyodbc
from ....domain.entities.annotation import BidAnnotation, int_color_to_hex
from ....domain.entities.layer import BidLayers, get_layer_uid_by_name, is_layer_visible
from ...parsers.position_parser import parse_position_bytes
from ...parsers.utils.parser import decode_value


def _resolve_color(raw_color: Any, default: str = "#FF0000") -> str:
    if isinstance(raw_color, int):
        return int_color_to_hex(raw_color)
    if isinstance(raw_color, str):
        return raw_color
    return default


class AnnotationReaderMixin:
    def _parse_bid_annotations_for_bid(
        self,
        connection: "pyodbc.Connection",
        bid_uid: str,
        bid_layers: BidLayers,
    ) -> List[BidAnnotation]:
        bid_annotations: List[BidAnnotation] = []
        annotation_layer_uid = get_layer_uid_by_name(bid_layers, "Annotation")
        annotation_layer_visible = is_layer_visible(bid_layers, annotation_layer_uid)

        def _layer(
            row_layer_uid: Any = None,
        ) -> tuple:
            if row_layer_uid is not None:
                return str(row_layer_uid), is_layer_visible(bid_layers, row_layer_uid)
            return annotation_layer_uid, annotation_layer_visible

        with connection.cursor() as cursor:
            try:
                cursor.execute(
                    """
                    SELECT UID, BidPageUID, BidLayerUID, Color, Position, Width
                    FROM BidAnnotationClouds
                    WHERE BidUID = ?
                    """,
                    bid_uid,
                )
                for row in cursor.fetchall():
                    position = parse_position_bytes(row.Position)
                    if position:
                        layer_uid, visible = _layer(row.BidLayerUID)
                        bid_annotations.append(
                            BidAnnotation(
                                uid=str(row.UID),
                                annotation_type="cloud",
                                page_uid=str(row.BidPageUID) if row.BidPageUID else "",
                                layer_uid=layer_uid,
                                position=position,
                                color=_resolve_color(row.Color),
                                width=float(row.Width) if row.Width else 2.0,
                                visible=visible,
                            )
                        )
            except pyodbc.Error as e:
                pass
            try:
                cursor.execute(
                    """
                    SELECT UID, BidPageUID, BidLayerUID, Color, Position, Width
                    FROM BidAnnotationOvals
                    WHERE BidUID = ?
                    """,
                    bid_uid,
                )
                for row in cursor.fetchall():
                    position = parse_position_bytes(row.Position)
                    if position:
                        layer_uid, visible = _layer(row.BidLayerUID)
                        bid_annotations.append(
                            BidAnnotation(
                                uid=str(row.UID),
                                annotation_type="oval",
                                page_uid=str(row.BidPageUID) if row.BidPageUID else "",
                                layer_uid=layer_uid,
                                position=position,
                                color=_resolve_color(row.Color),
                                width=float(row.Width) if row.Width else 2.0,
                                visible=visible,
                            )
                        )
            except pyodbc.Error as e:
                pass
            try:
                cursor.execute(
                    """
                    SELECT UID, BidPageUID, BidLayerUID, Color, Position, Width
                    FROM BidAnnotationPolygons
                    WHERE BidUID = ?
                    """,
                    bid_uid,
                )
                for row in cursor.fetchall():
                    position = parse_position_bytes(row.Position)
                    if position:
                        layer_uid, visible = _layer(row.BidLayerUID)
                        bid_annotations.append(
                            BidAnnotation(
                                uid=str(row.UID),
                                annotation_type="polygon",
                                page_uid=str(row.BidPageUID) if row.BidPageUID else "",
                                layer_uid=layer_uid,
                                position=position,
                                color=_resolve_color(row.Color),
                                width=float(row.Width) if row.Width else 2.0,
                                visible=visible,
                            )
                        )
            except pyodbc.Error as e:
                pass
            try:
                cursor.execute(
                    """
                    SELECT UID, BidPageUID, BidLayerUID, Color, Position, Width
                    FROM BidAnnotationRects
                    WHERE BidUID = ?
                    """,
                    bid_uid,
                )
                for row in cursor.fetchall():
                    position = parse_position_bytes(row.Position)
                    if position:
                        layer_uid, visible = _layer(row.BidLayerUID)
                        bid_annotations.append(
                            BidAnnotation(
                                uid=str(row.UID),
                                annotation_type="rect",
                                page_uid=str(row.BidPageUID) if row.BidPageUID else "",
                                layer_uid=layer_uid,
                                position=position,
                                color=_resolve_color(row.Color),
                                width=float(row.Width) if row.Width else 2.0,
                                visible=visible,
                            )
                        )
            except pyodbc.Error as e:
                pass
            try:
                cursor.execute(
                    """
                    SELECT UID, BidPageUID, Color, Position, Width
                    FROM BidAnnoInk
                    WHERE BidUID = ?
                    """,
                    bid_uid,
                )
                for row in cursor.fetchall():
                    position = parse_position_bytes(row.Position)
                    if position:
                        layer_uid, visible = _layer()
                        bid_annotations.append(
                            BidAnnotation(
                                uid=str(row.UID),
                                annotation_type="ink",
                                page_uid=str(row.BidPageUID) if row.BidPageUID else "",
                                layer_uid=layer_uid,
                                position=position,
                                color=_resolve_color(row.Color),
                                width=float(row.Width) if row.Width else 2.0,
                                visible=visible,
                            )
                        )
            except pyodbc.Error as e:
                pass
            try:
                cursor.execute(
                    """
                    SELECT UID, BidPageUID, BidTakeoffFromUID, BidTakeoffToUID,
                           Position, Color, Width
                    FROM BidALines
                    WHERE BidUID = ?
                    """,
                    bid_uid,
                )
                for row in cursor.fetchall():
                    position = parse_position_bytes(row.Position)
                    if position:
                        layer_uid, visible = _layer()
                        props = {}
                        if row.BidTakeoffFromUID is not None:
                            props["BidTakeoffFromUID"] = str(row.BidTakeoffFromUID)
                        if row.BidTakeoffToUID is not None:
                            props["BidTakeoffToUID"] = str(row.BidTakeoffToUID)
                        bid_annotations.append(
                            BidAnnotation(
                                uid=str(row.UID),
                                annotation_type="line",
                                page_uid=str(row.BidPageUID) if row.BidPageUID else "",
                                layer_uid=layer_uid,
                                position=position,
                                color=_resolve_color(row.Color),
                                width=float(row.Width) if row.Width else 2.0,
                                properties=props,
                                visible=visible,
                            )
                        )
            except pyodbc.Error as e:
                pass
            try:
                cursor.execute(
                    """
                    SELECT UID, BidPageUID, BidTakeoffFromUID, BidTakeoffToUID,
                           Position, Color, Width
                    FROM BidArrows
                    WHERE BidUID = ?
                    """,
                    bid_uid,
                )
                for row in cursor.fetchall():
                    position = parse_position_bytes(row.Position)
                    if position:
                        layer_uid, visible = _layer()
                        props = {}
                        if row.BidTakeoffFromUID is not None:
                            props["BidTakeoffFromUID"] = str(row.BidTakeoffFromUID)
                        if row.BidTakeoffToUID is not None:
                            props["BidTakeoffToUID"] = str(row.BidTakeoffToUID)
                        bid_annotations.append(
                            BidAnnotation(
                                uid=str(row.UID),
                                annotation_type="arrow",
                                page_uid=str(row.BidPageUID) if row.BidPageUID else "",
                                layer_uid=layer_uid,
                                position=position,
                                color=_resolve_color(row.Color),
                                width=float(row.Width) if row.Width else 2.0,
                                properties=props,
                                visible=visible,
                            )
                        )
            except pyodbc.Error as e:
                pass
            try:
                cursor.execute(
                    """
                    SELECT UID, BidPageUID, BidLayerUID, Name, FontName, FontColor,
                           FontSize, FontBold, FontItalic, FontUnderline, TextAlign,
                           Position
                    FROM BidTexts
                    WHERE BidUID = ?
                    """,
                    bid_uid,
                )
                for row in cursor.fetchall():
                    position = parse_position_bytes(row.Position)
                    if position and len(position) >= 4:
                        name_bytes = row.Name if isinstance(row.Name, bytes) else None
                        name_str = name_bytes.decode("latin-1") if name_bytes else ""
                        name_str = (
                            name_str.replace("\x00", "").replace("\r\n", "\n").strip()
                        )
                        layer_uid, visible = _layer(row.BidLayerUID)
                        bid_annotations.append(
                            BidAnnotation(
                                uid=str(row.UID),
                                annotation_type="text",
                                page_uid=str(row.BidPageUID) if row.BidPageUID else "",
                                layer_uid=layer_uid,
                                position=position,
                                color=_resolve_color(row.FontColor),
                                width=0.0,
                                properties={
                                    "Text": name_str,
                                    "FontColor": row.FontColor,
                                    "FontName": (
                                        str(row.FontName) if row.FontName else "Arial"
                                    ),
                                    "FontSize": (
                                        int(row.FontSize) if row.FontSize else 12
                                    ),
                                    "FontBold": bool(row.FontBold),
                                    "FontItalic": bool(row.FontItalic),
                                    "FontUnderline": bool(row.FontUnderline),
                                    "TextAlign": (
                                        int(row.TextAlign) if row.TextAlign else 0
                                    ),
                                },
                                visible=visible,
                            )
                        )
            except pyodbc.Error as e:
                pass
            try:
                cursor.execute(
                    """
                    SELECT UID, BidPageUID, BidLayerUID, Color, Position
                    FROM BidHighlights
                    WHERE BidUID = ?
                    """,
                    bid_uid,
                )
                for row in cursor.fetchall():
                    position = parse_position_bytes(row.Position)
                    if position:
                        layer_uid, visible = _layer(row.BidLayerUID)
                        bid_annotations.append(
                            BidAnnotation(
                                uid=str(row.UID),
                                annotation_type="highlight",
                                page_uid=str(row.BidPageUID) if row.BidPageUID else "",
                                layer_uid=layer_uid,
                                position=position,
                                color=_resolve_color(row.Color),
                                width=0.0,
                                visible=visible,
                            )
                        )
            except pyodbc.Error as e:
                pass
            try:
                cursor.execute(
                    """
                    SELECT UID, BidPageUID, Name, Position
                    FROM BidNamedViews
                    WHERE BidUID = ?
                    """,
                    bid_uid,
                )
                for row in cursor.fetchall():
                    position = parse_position_bytes(row.Position)
                    if position:
                        layer_uid, visible = _layer()
                        name_str = decode_value(row.Name).strip()
                        bid_annotations.append(
                            BidAnnotation(
                                uid=str(row.UID),
                                annotation_type="namedview",
                                page_uid=str(row.BidPageUID) if row.BidPageUID else "",
                                layer_uid=layer_uid,
                                position=position,
                                color="#008000",
                                width=2.0,
                                properties={"Text": name_str},
                                visible=visible,
                            )
                        )
            except pyodbc.Error as e:
                pass
            try:
                cursor.execute(
                    """
                    SELECT UID, BidPageUID, BidPageViewUID, BidLayerUID, Color, Position
                    FROM BidHotLinks
                    WHERE BidUID = ?
                    """,
                    bid_uid,
                )
                for row in cursor.fetchall():
                    position = parse_position_bytes(row.Position)
                    if position:
                        layer_uid, visible = _layer(row.BidLayerUID)
                        bid_annotations.append(
                            BidAnnotation(
                                uid=str(row.UID),
                                annotation_type="hotlink",
                                page_uid=str(row.BidPageUID) if row.BidPageUID else "",
                                layer_uid=layer_uid,
                                position=position,
                                color=_resolve_color(row.Color),
                                width=2.0,
                                properties={
                                    "BidPageViewUID": (
                                        str(row.BidPageViewUID)
                                        if row.BidPageViewUID
                                        else None
                                    ),
                                },
                                visible=visible,
                            )
                        )
            except pyodbc.Error as e:
                pass
            try:
                cursor.execute(
                    """
                    SELECT UID, BidPageUID, BidLayerUID, Name, FontName, FontColor,
                           FontSize, FontBold, FontItalic, FontUnderline, TextAlign,
                           Position, Color, Width
                    FROM BidCallOuts
                    WHERE BidUID = ?
                    """,
                    bid_uid,
                )
                for row in cursor.fetchall():
                    position = parse_position_bytes(row.Position)
                    if position:
                        name_bytes = row.Name if isinstance(row.Name, bytes) else None
                        name_str = name_bytes.decode("latin-1") if name_bytes else ""
                        name_str = (
                            name_str.replace("\x00", "").replace("\r\n", "\n").strip()
                        )
                        layer_uid, visible = _layer(row.BidLayerUID)
                        bid_annotations.append(
                            BidAnnotation(
                                uid=str(row.UID),
                                annotation_type="callout",
                                page_uid=str(row.BidPageUID) if row.BidPageUID else "",
                                layer_uid=layer_uid,
                                position=position,
                                color=_resolve_color(row.Color),
                                width=float(row.Width) if row.Width else 2.0,
                                properties={
                                    "Text": name_str,
                                    "FontColor": row.FontColor,
                                    "FontName": (
                                        str(row.FontName) if row.FontName else "Arial"
                                    ),
                                    "FontSize": (
                                        int(row.FontSize) if row.FontSize else 12
                                    ),
                                    "FontBold": bool(row.FontBold),
                                    "FontItalic": bool(row.FontItalic),
                                    "FontUnderline": bool(row.FontUnderline),
                                    "TextAlign": (
                                        int(row.TextAlign) if row.TextAlign else 0
                                    ),
                                },
                                visible=visible,
                            )
                        )
            except pyodbc.Error as e:
                pass
        return bid_annotations
