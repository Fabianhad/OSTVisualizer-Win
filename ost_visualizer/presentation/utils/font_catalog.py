from __future__ import annotations
from PySide6 import QtGui
from ...domain.entities.font_definition import FontDefinition


def installed_font_families() -> tuple[str, ...]:
    return tuple(sorted(QtGui.QFontDatabase.families(), key=str.casefold))


def _font_traits(font: QtGui.QFont) -> tuple[int, bool]:
    return (700 if font.bold() else 400, font.italic())


def lossless_font_styles(family: str) -> tuple[str, ...]:
    styles: list[str] = []
    for style_name in QtGui.QFontDatabase.styles(family):
        candidate = QtGui.QFontDatabase.font(family, style_name, 12)
        weight, italic = _font_traits(candidate)
        recreated = QtGui.QFont(family, 12)
        recreated.setBold(weight == 700)
        recreated.setItalic(italic)
        candidate_info = QtGui.QFontInfo(candidate)
        recreated_info = QtGui.QFontInfo(recreated)
        if (
            candidate_info.family().casefold() == recreated_info.family().casefold()
            and candidate_info.styleName().casefold()
            == recreated_info.styleName().casefold()
        ):
            styles.append(style_name)
    return tuple(styles)


def _matching_family(requested: str, families: tuple[str, ...]) -> str | None:
    by_name = {family.casefold(): family for family in families}
    return by_name.get(requested.casefold())


def _matching_trait_style(
    family: str,
    styles: tuple[str, ...],
    definition: FontDefinition,
) -> str | None:
    for style_name in styles:
        candidate = QtGui.QFontDatabase.font(family, style_name, definition.point_size)
        if _font_traits(candidate) == (definition.weight, definition.italic):
            return style_name
    return None


def resolve_font_definition(definition: FontDefinition) -> FontDefinition:
    if QtGui.QGuiApplication.instance() is None:
        raise RuntimeError("Font resolution requires an active Qt GUI application")
    families = installed_font_families()
    requested_family = _matching_family(definition.family, families)
    if requested_family is not None:
        styles = lossless_font_styles(requested_family)
        by_name = {style.casefold(): style for style in styles}
        style_name = by_name.get(definition.style_name.casefold())
        if style_name is not None:
            candidate = QtGui.QFontDatabase.font(
                requested_family,
                style_name,
                definition.point_size,
            )
            if _font_traits(candidate) != (definition.weight, definition.italic):
                style_name = None
        if style_name is None:
            style_name = _matching_trait_style(requested_family, styles, definition)
        if style_name is not None:
            return FontDefinition(
                family=requested_family,
                style_name=style_name,
                point_size=definition.point_size,
                weight=definition.weight,
                italic=definition.italic,
                underline=definition.underline,
            )
    arial_family = _matching_family("Arial", families)
    system_family = QtGui.QFontDatabase.systemFont(
        QtGui.QFontDatabase.SystemFont.GeneralFont
    ).family()
    fallback_families = tuple(
        dict.fromkeys(
            family for family in (arial_family, system_family) if family is not None
        )
    )
    for family in fallback_families:
        style_name = _matching_trait_style(
            family, lossless_font_styles(family), definition
        )
        if style_name is not None:
            break
    else:
        raise ValueError(
            "No installed font family has a lossless style matching "
            f"weight={definition.weight} and italic={definition.italic}"
        )
    return FontDefinition(
        family=family,
        style_name=style_name,
        point_size=definition.point_size,
        weight=definition.weight,
        italic=definition.italic,
        underline=definition.underline,
    )


def qfont_from_resolved_definition(definition: FontDefinition) -> QtGui.QFont:
    font = QtGui.QFont(definition.family, definition.point_size)
    font.setStyleName(definition.style_name)
    font.setBold(definition.weight == 700)
    font.setItalic(definition.italic)
    font.setUnderline(definition.underline)
    return font
