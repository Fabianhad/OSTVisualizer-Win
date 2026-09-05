import logging
from typing import Callable, List, Optional, Set
from PySide6 import QtWidgets
from PySide6.QtCore import Signal
from shiboken6 import isValid
from ...domain.entities.identity_refs import BidRef
from ..components.area_combo import AreaComboBox
from ..components.resizable_combo import ResizableComboBox
from ..config import (
    COMPACT_MARGINS,
    COMPACT_SPACING,
    NO_MARGINS,
    SCALE_TOOLTIP,
    VIEWER_AREA_COMBO_WIDTH,
    VIEWER_SCALE_COMBO_WIDTH,
)
from ..dialogs.areas_dialog import BidAreaPickerDialog
from ..managers.ui_access_manager import Feature
from ..utils.button_policy import apply_no_highlight_button_policy
from ..utils.dialog import delete_later_if_valid
from ..utils.ost_blocking import exec_with_ost_blocking
from ..utils.scales import ALL_SCALES, format_custom_scale

logger = logging.getLogger(__name__)
_DEFAULT_AREA_UID = "0"
_CUSTOM_SCALE_DATA = "__custom_scale__"
_DROPDOWN_KEY_SCALE = "main_scale"
_DROPDOWN_KEY_AREA = "main_area"


class PageSettingsBar(QtWidgets.QWidget):
    scale_change_requested = Signal(str, str, float, float)
    custom_scale_requested = Signal(str, str)
    area_change_requested = Signal(str, str, str)
    dropdown_size_changed = Signal()
    presentation_state_changed = Signal()

    def __init__(
        self,
        icon_provider,
        event_bus,
        refresh_areas_fn: Callable,
        ui_access_manager,
        workspace_state_model,
        load_areas_fn: Optional[Callable] = None,
        save_areas_fn: Optional[Callable] = None,
        save_areas_async_fn: Optional[Callable] = None,
        parent=None,
        *,
        uses_async_areas_fn: Optional[Callable[[str], bool]] = None,
    ):
        super().__init__(parent)
        self._icon_provider = icon_provider
        self._event_bus = event_bus
        self._access = ui_access_manager
        self._workspace_state_model = workspace_state_model
        self._load_areas_fn = load_areas_fn
        self._save_areas_fn = save_areas_fn
        self._save_areas_async_fn = save_areas_async_fn
        self._uses_async_areas_fn = uses_async_areas_fn
        self._refresh_areas_fn = refresh_areas_fn
        self._bid_ref: Optional[BidRef] = None
        self._page_uid: Optional[str] = None
        self._interactive: bool = False
        self._bid_areas_in_use: Optional[Set] = None
        self._page_areas_in_use: Optional[Set] = None
        self._current_scale_index: int = -1
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(*NO_MARGINS)
        layout.setSpacing(COMPACT_SPACING)
        layout.addSpacing(COMPACT_MARGINS[0])
        self.scale_combo = ResizableComboBox()
        self.scale_combo.setFixedWidth(VIEWER_SCALE_COMBO_WIDTH)
        self.scale_combo.setEnabled(False)
        self.scale_combo.setToolTip(SCALE_TOOLTIP)
        for sf1, sf2, label in ALL_SCALES:
            self.scale_combo.addItem(label, (sf1, sf2))
        self._custom_scale_index = self.scale_combo.count()
        self.scale_combo.addItem("Custom scale", _CUSTOM_SCALE_DATA)
        self.scale_combo.setCurrentIndex(-1)
        self.scale_combo.activated.connect(self._on_scale_activated)
        self.scale_combo.popup_size_changed.connect(self.dropdown_size_changed)
        layout.addWidget(self.scale_combo)
        layout.addWidget(QtWidgets.QLabel("Area"))
        self.area_combo = AreaComboBox()
        self.area_combo.setFixedWidth(VIEWER_AREA_COMBO_WIDTH)
        self.area_combo.setEnabled(False)
        self.area_combo.setToolTip("Area")
        self.area_combo.area_activated.connect(self._on_area_activated)
        self.area_combo.popup_size_changed.connect(self.dropdown_size_changed)
        layout.addWidget(self.area_combo)
        self.area_browse_btn = QtWidgets.QPushButton("...")
        apply_no_highlight_button_policy(self.area_browse_btn)
        self.area_browse_btn.setFixedWidth(24)
        self.area_browse_btn.setEnabled(False)
        self.area_browse_btn.clicked.connect(self._on_area_browse)
        layout.addWidget(self.area_browse_btn)

    def load_bid_areas(
        self,
        bid_ref: BidRef,
        areas: Optional[List] = None,
        areas_with_takeoff: Optional[Set[str]] = None,
        selected_uid: Optional[str] = None,
    ) -> None:
        self._bid_ref = bid_ref
        self._bid_areas_in_use = (
            set(areas_with_takeoff) if areas_with_takeoff is not None else None
        )
        if areas is None:
            areas = []
            if self._load_areas_fn:
                try:
                    areas = self._load_areas_fn(bid_ref.file_path, bid_ref.bid_uid)
                except Exception:
                    logger.exception("Failed to load bid areas for bar")
        signals_were_blocked = self.area_combo.blockSignals(True)
        try:
            self.area_combo.load_areas(
                areas,
                areas_with_takeoff=self._bid_areas_in_use,
                selected_uid=selected_uid,
            )
        finally:
            self.area_combo.blockSignals(signals_were_blocked)
        self.presentation_state_changed.emit()

    def update_bold_states(self, areas_with_takeoff: Set) -> None:
        self.area_combo.update_bold_states(areas_with_takeoff)
        self.presentation_state_changed.emit()

    def update_area_usage(
        self,
        bid_areas_with_takeoff: Optional[Set[str]] = None,
        page_areas_with_takeoff: Optional[Set[str]] = None,
    ) -> None:
        if bid_areas_with_takeoff is not None:
            self._bid_areas_in_use = set(bid_areas_with_takeoff)
        if page_areas_with_takeoff is not None:
            self._page_areas_in_use = set(page_areas_with_takeoff)
            self.update_bold_states(self._page_areas_in_use)

    def load_page(
        self,
        page_uid: str,
        sf1: float,
        sf2: float,
        selected_area_uid: Optional[str],
        areas_with_takeoff: Optional[Set] = None,
    ) -> None:
        self._page_uid = page_uid
        signals_were_blocked = self.scale_combo.blockSignals(True)
        try:
            self.scale_combo.setItemText(self._custom_scale_index, "Custom scale")
            scale_idx = self._predefined_scale_index(sf1, sf2)
            if scale_idx < 0:
                custom_label = format_custom_scale(sf1, sf2)
                if custom_label:
                    self.scale_combo.setItemText(self._custom_scale_index, custom_label)
                    scale_idx = self._custom_scale_index
            self._current_scale_index = scale_idx
            self.scale_combo.setCurrentIndex(scale_idx)
        finally:
            self.scale_combo.blockSignals(signals_were_blocked)
        signals_were_blocked = self.area_combo.blockSignals(True)
        try:
            self.area_combo.set_current_area_uid(selected_area_uid or "")
            if areas_with_takeoff is not None:
                self._page_areas_in_use = set(areas_with_takeoff)
                self.area_combo.update_bold_states(self._page_areas_in_use)
        finally:
            self.area_combo.blockSignals(signals_were_blocked)
        if self._interactive:
            self._sync_interactive_controls()
        self.presentation_state_changed.emit()

    def _predefined_scale_index(self, sf1: float, sf2: float) -> int:
        try:
            target_sf1 = float(sf1)
            target_sf2 = float(sf2)
        except (TypeError, ValueError):
            return -1
        for index in range(self._custom_scale_index):
            scale_sf1, scale_sf2 = self.scale_combo.itemData(index)
            if (
                abs(scale_sf1 - target_sf1) < 1e-9
                and abs(scale_sf2 - target_sf2) < 1e-9
            ):
                return index
        return -1

    def _sync_interactive_controls(self) -> None:
        self.scale_combo.setEnabled(True)
        self.area_combo.setEnabled(True)
        self.area_browse_btn.setEnabled(self._bid_ref is not None)

    def get_dropdown_popup_sizes(self) -> dict[str, list[int]]:
        return {
            _DROPDOWN_KEY_SCALE: self.scale_combo.get_popup_size(),
            _DROPDOWN_KEY_AREA: self.area_combo.get_popup_size(),
        }

    def set_dropdown_popup_sizes(self, sizes: dict[str, list[int]]) -> None:
        self.scale_combo.set_popup_size(sizes.get(_DROPDOWN_KEY_SCALE, []))
        self.area_combo.set_popup_size(sizes.get(_DROPDOWN_KEY_AREA, []))

    def clear_bid(self) -> None:
        self._bid_ref = None
        self._bid_areas_in_use = None
        area_signals_were_blocked = self.area_combo.blockSignals(True)
        try:
            self.area_combo.clear_areas()
        finally:
            self.area_combo.blockSignals(area_signals_were_blocked)
        self._clear_page_projection()
        self.presentation_state_changed.emit()

    def clear_page(self) -> None:
        self._clear_page_projection()
        self.presentation_state_changed.emit()

    def _clear_page_projection(self) -> None:
        self._page_uid = None
        self._page_areas_in_use = None
        self._current_scale_index = -1
        area_signals_were_blocked = self.area_combo.blockSignals(True)
        try:
            self.area_combo.set_current_area_uid("")
            self.area_combo.update_bold_states(set())
        finally:
            self.area_combo.blockSignals(area_signals_were_blocked)
        signals_were_blocked = self.scale_combo.blockSignals(True)
        try:
            self.scale_combo.setCurrentIndex(-1)
            self.scale_combo.setItemText(self._custom_scale_index, "Custom scale")
        finally:
            self.scale_combo.blockSignals(signals_were_blocked)
        for w in (self.scale_combo, self.area_combo, self.area_browse_btn):
            w.setEnabled(False)

    def set_interactive(self, enabled: bool) -> None:
        self._interactive = enabled
        if not enabled:
            for w in (self.scale_combo, self.area_combo, self.area_browse_btn):
                w.setEnabled(False)
        elif self._page_uid:
            self._sync_interactive_controls()
        self.presentation_state_changed.emit()

    def _on_area_browse(self) -> None:
        if (
            not self._access.is_allowed(Feature.EDIT_PAGE_SETTINGS)
            or not self._bid_ref
            or not self._load_areas_fn
        ):
            return
        bid_ref = self._bid_ref
        sync_save_fn = self._save_areas_fn
        async_save_fn = self._save_areas_async_fn
        use_async_save = async_save_fn is not None and (
            self._uses_async_areas_fn is None
            or self._uses_async_areas_fn(bid_ref.file_path)
        )
        if sync_save_fn is None and not use_async_save:
            return
        page_uid = self._page_uid
        areas = []
        try:
            areas = self._load_areas_fn(bid_ref.file_path, bid_ref.bid_uid)
        except Exception:
            logger.exception("Failed to load bid areas for picker")
            return
        prev_area_uid = self.area_combo.get_current_area_uid()
        if sync_save_fn is not None:

            def _save_fn(changes: dict):
                if (
                    not self._access.is_allowed(Feature.EDIT_PAGE_SETTINGS)
                    or self._bid_ref != bid_ref
                ):
                    return None
                return sync_save_fn(
                    bid_ref.file_path,
                    bid_ref.bid_uid,
                    changes,
                    publish_database_refreshed_after_write=False,
                )

        else:
            _save_fn = None
        if use_async_save:

            def _save_async_fn(changes: dict, completed) -> bool:
                if (
                    not self._access.is_allowed(Feature.EDIT_PAGE_SETTINGS)
                    or self._bid_ref != bid_ref
                ):
                    completed(False, None)
                    return False
                return bool(async_save_fn(bid_ref, changes, completed))

        else:
            _save_async_fn = None

        def _on_saved() -> None:
            if self._bid_ref != bid_ref:
                return
            self.load_bid_areas(
                bid_ref,
                areas_with_takeoff=self._bid_areas_in_use,
                selected_uid=self.area_combo.get_current_area_uid(),
            )

        dlg = BidAreaPickerDialog(
            icon_provider=self._icon_provider,
            parent=self,
            bid_areas=areas,
            save_fn=_save_fn,
            save_async_fn=_save_async_fn,
            used_uids=self._bid_areas_in_use,
            on_saved_fn=_on_saved,
            bid_ref=bid_ref,
            workspace_state_model=self._workspace_state_model,
        )
        selected_uid = None
        saved_changes = False
        try:
            result = exec_with_ost_blocking(dlg, self._event_bus)
            if not isValid(self) or not isValid(dlg):
                return
            if result == QtWidgets.QDialog.DialogCode.Accepted:
                selected_uid = dlg.get_selected_uid()
            saved_changes = dlg.has_saved_changes()
        finally:
            try:
                dlg.cleanup()
            finally:
                delete_later_if_valid(dlg)
        if saved_changes and not use_async_save:
            self._refresh_areas_fn(bid_ref.file_path)
        if self._bid_ref != bid_ref or self._page_uid != page_uid:
            return
        self.load_bid_areas(bid_ref, areas_with_takeoff=self._bid_areas_in_use)
        if self._page_areas_in_use is not None:
            self.update_bold_states(self._page_areas_in_use)
        target_uid = selected_uid if selected_uid is not None else prev_area_uid
        self.area_combo.set_current_area_uid(target_uid)
        if selected_uid is not None:
            self._on_area_activated(target_uid)

    def _on_scale_activated(self, index: int) -> None:
        if (
            not self._access.is_allowed(Feature.EDIT_PAGE_SETTINGS)
            or not self._interactive
            or not self._bid_ref
            or not self._page_uid
        ):
            return
        data = self.scale_combo.itemData(index)
        if data == _CUSTOM_SCALE_DATA:
            signals_were_blocked = self.scale_combo.blockSignals(True)
            try:
                self.scale_combo.setCurrentIndex(self._current_scale_index)
            finally:
                self.scale_combo.blockSignals(signals_were_blocked)
            self.custom_scale_requested.emit(self._bid_ref.file_path, self._page_uid)
        elif data:
            self._current_scale_index = index
            sf1, sf2 = data
            self.scale_change_requested.emit(
                self._bid_ref.file_path, self._page_uid, sf1, sf2
            )

    def get_current_area_uid(self) -> str:
        return self.area_combo.get_current_area_uid() or _DEFAULT_AREA_UID

    def get_selected_area_uid(self) -> str:
        return self.area_combo.get_current_area_uid()

    def _on_area_activated(self, area_uid: str) -> None:
        if (
            not self._access.is_allowed(Feature.EDIT_PAGE_SETTINGS)
            or not self._interactive
            or not self._bid_ref
            or not self._page_uid
        ):
            return
        self.area_change_requested.emit(
            self._bid_ref.file_path, self._page_uid, area_uid or ""
        )
