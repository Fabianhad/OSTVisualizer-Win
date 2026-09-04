from __future__ import annotations
from PySide6 import QtWidgets


class AmbiguousComboIdentityError(ValueError):
    """An editable combo label matches more than one authoritative item."""


def resolve_editable_combo_uid(combo: QtWidgets.QComboBox) -> object | None:
    text = combo.currentText().strip()
    if not text:
        return None
    normalized = text.lower()
    current_index = combo.currentIndex()
    if (
        current_index >= 0
        and combo.itemText(current_index).strip().lower() == normalized
    ):
        return combo.itemData(current_index)
    matching = [
        combo.itemData(index)
        for index in range(combo.count())
        if combo.itemText(index).strip().lower() == normalized
    ]
    if len(matching) > 1:
        raise AmbiguousComboIdentityError(
            f'"{text}" matches more than one item. Select the intended item '
            "from the list."
        )
    return matching[0] if matching else None
