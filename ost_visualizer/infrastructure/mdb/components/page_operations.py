import pyodbc
from .constants import PAGE_CONTENT_TABLES
from .overlay_rect import default_overlay_rect


class PageOperationsMixin:
    _POSITION_TABLES = PAGE_CONTENT_TABLES + ("BidTypGroupViews",)

    def save_page_scale(
        self, db_path: str, page_uid: str, sf1: float, sf2: float
    ) -> bool:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(
                    schema, "BidPages", ("UID", "ScaleFactor1", "ScaleFactor2")
                )
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT [ScaleFactor1], [ScaleFactor2] FROM [BidPages] WHERE [UID]=?",
                    int(page_uid),
                )
                row = cursor.fetchone()
                if row and row[0] and row[1]:
                    old_sf1 = float(row[0])
                    old_sf2 = float(row[1])
                    old_ratio = old_sf2 / old_sf1 if old_sf1 else 1.0
                    new_ratio = sf2 / sf1 if sf1 else 1.0
                    factor = new_ratio / old_ratio if old_ratio else 1.0
                    if abs(factor - 1.0) > 1e-9:
                        self._rescale_page_positions(
                            cursor, schema, int(page_uid), factor
                        )
                cursor.execute(
                    "UPDATE [BidPages] SET [ScaleFactor1]=?, [ScaleFactor2]=? WHERE [UID]=?",
                    sf1,
                    sf2,
                    int(page_uid),
                )
                return True
        except Exception:
            self.logger.exception(
                "Failed to save page scale for page %s in %s", page_uid, db_path
            )
            return False

    def save_page_name(self, db_path: str, page_uid: str, name: str) -> bool:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                cursor = conn.cursor()
                return self._execute_update_values(
                    cursor,
                    schema,
                    "BidPages",
                    {"Name": name},
                    ("UID", "Name"),
                    "[UID]=?",
                    [int(page_uid)],
                    "save_page_name",
                )
        except Exception:
            self.logger.exception(
                "Failed to save page name for page %s in %s", page_uid, db_path
            )
            return False

    def _rescale_page_positions(
        self,
        cursor: "pyodbc.Cursor",
        schema,
        page_uid: int,
        factor: float,
    ) -> None:
        for table in self._POSITION_TABLES:
            try:
                if schema.optional_table_missing(table):
                    continue
                if not (
                    schema.column_exists(table, "UID")
                    and schema.column_exists(table, "BidPageUID")
                    and schema.column_exists(table, "Position")
                ):
                    continue
                cursor.execute(
                    f"SELECT UID, Position FROM [{table}] WHERE BidPageUID=?",
                    page_uid,
                )
                rows = cursor.fetchall()
                for r in rows:
                    raw = r.Position
                    if not raw:
                        continue
                    if isinstance(raw, bytes):
                        pos_str = raw.decode("utf-8", errors="ignore")
                    else:
                        pos_str = str(raw)
                    parts = [p.strip() for p in pos_str.split(";") if p.strip()]
                    scaled = []
                    for p in parts:
                        try:
                            scaled.append(float(p) * factor)
                        except ValueError:
                            scaled.append(p)
                    new_str = ";".join(
                        (f"{v:.6g}" if isinstance(v, float) else v) for v in scaled
                    )
                    new_bytes = new_str.encode("utf-8")
                    cursor.execute(
                        f"UPDATE [{table}] SET [Position]=? WHERE [UID]=?",
                        new_bytes,
                        int(r.UID),
                    )
            except (pyodbc.Error, TypeError, ValueError):
                pass

    def save_page_view_state(
        self,
        db_path: str,
        page_uid: str,
        zoom_fac: float,
        current_x: float,
        current_y: float,
    ) -> bool:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                values = {
                    "ZoomFac": zoom_fac,
                    "CurrentX": current_x,
                    "CurrentY": current_y,
                }
                cursor = conn.cursor()
                self._execute_update_values(
                    cursor,
                    schema,
                    "BidPages",
                    values,
                    ("UID",),
                    "[UID]=?",
                    [int(page_uid)],
                    "save_page_view_state",
                    allow_empty=True,
                )
                return True
        except Exception:
            self.logger.exception(
                "Failed to save page view state for page %s in %s", page_uid, db_path
            )
            return False

    def save_page_show_mode(self, db_path: str, page_uid: str, show_mode: int) -> bool:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                self._require_write_columns(schema, "BidPages", ("UID", "Show"))
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE [BidPages] SET [Show]=? WHERE [UID]=?",
                    int(show_mode),
                    int(page_uid),
                )
                return True
        except Exception:
            self.logger.exception(
                "Failed to save page show mode for page %s in %s", page_uid, db_path
            )
            return False

    def save_page_overlay_image(
        self, db_path: str, page_uid: str, overlay_image_path: str
    ) -> bool:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                cursor = conn.cursor()
                values = {"OverlayImagePath": overlay_image_path or ""}
                if schema.column_exists("BidPages", "OverlayRect"):
                    if overlay_image_path:
                        cursor.execute(
                            "SELECT [Width], [Height] FROM [BidPages] WHERE [UID]=?",
                            int(page_uid),
                        )
                        row = cursor.fetchone()
                        if row is not None:
                            values["OverlayRect"] = default_overlay_rect(
                                row.Width, row.Height
                            )
                    else:
                        values["OverlayRect"] = ""
                return self._execute_update_values(
                    cursor,
                    schema,
                    "BidPages",
                    values,
                    ("UID",),
                    "[UID]=?",
                    [int(page_uid)],
                    "save_page_overlay_image",
                    allow_empty=True,
                )
        except Exception:
            self.logger.exception(
                "Failed to save page overlay image for page %s in %s",
                page_uid,
                db_path,
            )
            return False

    def save_page_overlay_rect(
        self,
        db_path: str,
        page_uid: str,
        overlay_rect: tuple[float, float, float, float],
    ) -> bool:
        try:
            rect_x, rect_y, rect_w, rect_h = overlay_rect
            rect_text = (
                f"{float(rect_x):.6f},{float(rect_y):.6f},"
                f"{float(rect_w):.6f},{float(rect_h):.6f}"
            )
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                cursor = conn.cursor()
                return self._execute_update_values(
                    cursor,
                    schema,
                    "BidPages",
                    {"OverlayRect": rect_text},
                    ("UID",),
                    "[UID]=?",
                    [int(page_uid)],
                    "save_page_overlay_rect",
                )
        except Exception:
            self.logger.exception(
                "Failed to save page overlay rect for page %s in %s",
                page_uid,
                db_path,
            )
            return False

    def save_page_invert(self, db_path: str, page_uid: str, invert: bool) -> bool:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                cursor = conn.cursor()
                return self._execute_update_values(
                    cursor,
                    schema,
                    "BidPages",
                    {"Invert": self._access_bool(invert)},
                    ("UID",),
                    "[UID]=?",
                    [int(page_uid)],
                    "save_page_invert",
                    allow_empty=True,
                )
        except Exception:
            self.logger.exception(
                "Failed to save page invert state for page %s in %s",
                page_uid,
                db_path,
            )
            return False

    def save_page_bitonal(self, db_path: str, page_uid: str, bitonal: bool) -> bool:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                cursor = conn.cursor()
                return self._execute_update_values(
                    cursor,
                    schema,
                    "BidPages",
                    {"Bitonal": self._access_bool(bitonal)},
                    ("UID",),
                    "[UID]=?",
                    [int(page_uid)],
                    "save_page_bitonal",
                    allow_empty=True,
                )
        except Exception:
            self.logger.exception(
                "Failed to save page bitonal state for page %s in %s",
                page_uid,
                db_path,
            )
            return False

    def save_page_image_adjustments(
        self,
        db_path: str,
        page_uids: list[str],
        rotation: int,
        flip_x: bool,
        flip_y: bool,
        invert: bool,
        bitonal: bool,
    ) -> bool:
        try:
            normalized_rotation = int(rotation or 0) % 360
            if normalized_rotation not in (0, 90, 180, 270):
                normalized_rotation = 0
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                cursor = conn.cursor()
                values = {
                    "Rotation": normalized_rotation,
                    "FlipX": self._access_bool(flip_x),
                    "FlipY": self._access_bool(flip_y),
                    "Invert": self._access_bool(invert),
                    "Bitonal": self._access_bool(bitonal),
                }
                for page_uid in page_uids:
                    self._execute_update_values(
                        cursor,
                        schema,
                        "BidPages",
                        values,
                        ("UID", "Rotation", "FlipX", "FlipY", "Invert", "Bitonal"),
                        "[UID]=?",
                        [int(page_uid)],
                        "save_page_image_adjustments",
                    )
                return True
        except Exception:
            self.logger.exception(
                "Failed to save page image adjustments in %s", db_path
            )
            return False

    def _access_bool(self, value: bool) -> int:
        return -1 if value else 0

    def save_page_area(self, db_path: str, page_uid: str, area_uid: str) -> bool:
        try:
            with self._connection(db_path) as conn:
                schema = self._schema(conn)
                if schema.optional_table_missing("BidPageSettings"):
                    raise RuntimeError(
                        "This OST database does not support page area settings."
                    )
                self._require_write_columns(
                    schema,
                    "BidPageSettings",
                    ("BidPageUID", "BidAreaUID", "BidAreaSelected"),
                )
                cursor = conn.cursor()
                if area_uid == "0":
                    cursor.execute(
                        "UPDATE [BidPageSettings] SET [BidAreaUID]=NULL, [BidAreaSelected]=1 WHERE [BidPageUID]=?",
                        int(page_uid),
                    )
                    if cursor.rowcount == 0:
                        cursor.execute(
                            "INSERT INTO [BidPageSettings] ([BidPageUID], [BidAreaUID], [BidAreaSelected]) VALUES (?, NULL, 1)",
                            int(page_uid),
                        )
                elif area_uid:
                    cursor.execute(
                        "UPDATE [BidPageSettings] SET [BidAreaUID]=?, [BidAreaSelected]=2 WHERE [BidPageUID]=?",
                        int(area_uid),
                        int(page_uid),
                    )
                    if cursor.rowcount == 0:
                        cursor.execute(
                            "INSERT INTO [BidPageSettings] ([BidPageUID], [BidAreaUID], [BidAreaSelected]) VALUES (?, ?, 2)",
                            int(page_uid),
                            int(area_uid),
                        )
                else:
                    cursor.execute(
                        "DELETE FROM [BidPageSettings] WHERE [BidPageUID]=?",
                        int(page_uid),
                    )
                return True
        except Exception:
            self.logger.exception(
                "Failed to save page area for page %s in %s", page_uid, db_path
            )
            return False
