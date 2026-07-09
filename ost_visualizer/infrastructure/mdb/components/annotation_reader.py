from typing import Any, List
import pyodbc
from ....domain.entities.annotation import BidAnnotation, int_color_to_hex
from ....domain.entities.layer import BidLayers
from ...parsers.utils.parser import decode_value
from ..mappers.annotation_mapper import MdbAnnotationLayerMapper
from ..schema_compatibility import MdbSchemaInspector
from .serialization import decode_annotation_text, parse_position_storage


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
        schema: MdbSchemaInspector,
    ) -> List[BidAnnotation]:
        bid_annotations: List[BidAnnotation] = []
        layer_mapper = MdbAnnotationLayerMapper(bid_layers)
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
                    position = parse_position_storage(row.Position)
                    if position:
                        layer_uid, visible = layer_mapper.resolve_layer(row.BidLayerUID)
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
            except pyodbc.Error:
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
                    position = parse_position_storage(row.Position)
                    if position:
                        layer_uid, visible = layer_mapper.resolve_layer(row.BidLayerUID)
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
            except pyodbc.Error:
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
                    position = parse_position_storage(row.Position)
                    if position:
                        layer_uid, visible = layer_mapper.resolve_layer(row.BidLayerUID)
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
            except pyodbc.Error:
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
                    position = parse_position_storage(row.Position)
                    if position:
                        layer_uid, visible = layer_mapper.resolve_layer(row.BidLayerUID)
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
            except pyodbc.Error:
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
                    position = parse_position_storage(row.Position)
                    if position:
                        layer_uid, visible = layer_mapper.resolve_layer()
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
            except pyodbc.Error:
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
                    position = parse_position_storage(row.Position)
                    if position:
                        layer_uid, visible = layer_mapper.resolve_layer()
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
            except pyodbc.Error:
                pass
            try:
                cursor.execute(
                    """
                    SELECT UID, BidPageUID, BidTakeoffFromUID, BidTakeoffToUID,
                           Position, FontName, FontColor, FontSize, FontBold,
                           FontItalic, FontUnderline
                    FROM BidDimensions
                    WHERE BidUID = ?
                    """,
                    bid_uid,
                )
                for row in cursor.fetchall():
                    position = parse_position_storage(row.Position)
                    if position:
                        layer_uid, visible = layer_mapper.resolve_layer()
                        props = {
                            "FontName": (
                                str(row.FontName) if row.FontName else "Arial"
                            ),
                            "FontColor": row.FontColor,
                            "FontSize": (int(row.FontSize) if row.FontSize else 10),
                            "FontBold": bool(row.FontBold),
                            "FontItalic": bool(row.FontItalic),
                            "FontUnderline": bool(row.FontUnderline),
                        }
                        if row.BidTakeoffFromUID is not None:
                            props["BidTakeoffFromUID"] = str(row.BidTakeoffFromUID)
                        if row.BidTakeoffToUID is not None:
                            props["BidTakeoffToUID"] = str(row.BidTakeoffToUID)
                        bid_annotations.append(
                            BidAnnotation(
                                uid=str(row.UID),
                                annotation_type="dimension",
                                page_uid=str(row.BidPageUID) if row.BidPageUID else "",
                                layer_uid=layer_uid,
                                position=position,
                                color=_resolve_color(row.FontColor),
                                width=1.0,
                                properties=props,
                                visible=visible,
                            )
                        )
            except pyodbc.Error:
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
                    position = parse_position_storage(row.Position)
                    if position:
                        layer_uid, visible = layer_mapper.resolve_layer()
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
            except pyodbc.Error:
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
                    position = parse_position_storage(row.Position)
                    if position and len(position) >= 4:
                        name_str = decode_annotation_text(row.Name)
                        layer_uid, visible = layer_mapper.resolve_layer(row.BidLayerUID)
                        props = {
                            "Text": name_str,
                            "FontColor": row.FontColor,
                            "FontName": (
                                str(row.FontName) if row.FontName else "Arial"
                            ),
                            "FontSize": (int(row.FontSize) if row.FontSize else 12),
                            "FontBold": bool(row.FontBold),
                            "FontItalic": bool(row.FontItalic),
                            "FontUnderline": bool(row.FontUnderline),
                            "TextAlign": (int(row.TextAlign) if row.TextAlign else 0),
                        }
                        annotation = BidAnnotation(
                            uid=str(row.UID),
                            annotation_type="text",
                            page_uid=str(row.BidPageUID) if row.BidPageUID else "",
                            layer_uid=layer_uid,
                            position=position,
                            color=_resolve_color(row.FontColor),
                            width=0.0,
                            properties=props,
                            visible=visible,
                        )
                        bid_annotations.append(annotation)
            except pyodbc.Error:
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
                    position = parse_position_storage(row.Position)
                    if position:
                        layer_uid, visible = layer_mapper.resolve_layer(row.BidLayerUID)
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
            except pyodbc.Error:
                pass
            try:
                color_column = schema.optional_column("BidNamedViews", "Color", "NULL")
                cursor.execute(
                    f"""
                    SELECT UID, BidPageUID, Name, {color_column}, Position
                    FROM BidNamedViews
                    WHERE BidUID = ?
                    """,
                    bid_uid,
                )
                for row in cursor.fetchall():
                    position = parse_position_storage(row.Position)
                    if position:
                        layer_uid, visible = layer_mapper.resolve_layer()
                        name_str = decode_value(row.Name).strip()
                        bid_annotations.append(
                            BidAnnotation(
                                uid=str(row.UID),
                                annotation_type="namedview",
                                page_uid=str(row.BidPageUID) if row.BidPageUID else "",
                                layer_uid=layer_uid,
                                position=position,
                                color=_resolve_color(row.Color, "#008000"),
                                width=2.0,
                                properties={"Text": name_str},
                                visible=visible,
                            )
                        )
            except pyodbc.Error:
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
                    position = parse_position_storage(row.Position)
                    if position:
                        layer_uid, visible = layer_mapper.resolve_layer(row.BidLayerUID)
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
            except pyodbc.Error:
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
                    position = parse_position_storage(row.Position)
                    if position:
                        name_str = decode_annotation_text(row.Name)
                        layer_uid, visible = layer_mapper.resolve_layer(row.BidLayerUID)
                        props = {
                            "Text": name_str,
                            "FontColor": row.FontColor,
                            "FontName": (
                                str(row.FontName) if row.FontName else "Arial"
                            ),
                            "FontSize": (int(row.FontSize) if row.FontSize else 12),
                            "FontBold": bool(row.FontBold),
                            "FontItalic": bool(row.FontItalic),
                            "FontUnderline": bool(row.FontUnderline),
                            "TextAlign": (int(row.TextAlign) if row.TextAlign else 0),
                        }
                        annotation = BidAnnotation(
                            uid=str(row.UID),
                            annotation_type="callout",
                            page_uid=str(row.BidPageUID) if row.BidPageUID else "",
                            layer_uid=layer_uid,
                            position=position,
                            color=_resolve_color(row.Color),
                            width=float(row.Width) if row.Width else 2.0,
                            properties=props,
                            visible=visible,
                        )
                        bid_annotations.append(annotation)
            except pyodbc.Error:
                pass
        return bid_annotations
