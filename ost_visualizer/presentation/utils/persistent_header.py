from __future__ import annotations
from collections.abc import Sequence
from PySide6 import QtCore, QtWidgets
from shiboken6 import isValid
from ...domain.aggregates.workspace_state_aggregate import WorkspaceStateAggregate
from ...domain.entities.workspace_state import HeaderLayoutState


class PersistentHeaderController(QtCore.QObject):
    def __init__(
        self,
        view: QtWidgets.QTreeWidget,
        view_id: str,
        column_keys: Sequence[str],
        workspace_state_model: WorkspaceStateAggregate,
        *,
        sorting: bool,
        movable: bool,
        persisted_width_keys: Sequence[str] | None = None,
        default_sort_column: str | None = None,
        default_sort_order: QtCore.Qt.SortOrder = QtCore.Qt.SortOrder.AscendingOrder,
    ) -> None:
        super().__init__(view)
        keys = tuple(column_keys)
        if (
            not view_id
            or not isinstance(view_id, str)
            or any(not isinstance(key, str) or not key for key in keys)
            or len(keys) != view.columnCount()
            or len(set(keys)) != len(keys)
        ):
            raise ValueError(f"Invalid semantic columns for header {view_id}")
        if default_sort_column is not None and default_sort_column not in keys:
            raise ValueError(f"Invalid default sort column for header {view_id}")
        self._view = view
        self._header = view.header()
        self._view_id = view_id
        self._column_keys = keys
        self._all_column_keys = keys
        self._workspace_state_model = workspace_state_model
        self._sorting = bool(sorting)
        self._movable = bool(movable)
        persisted_keys = frozenset(
            persisted_width_keys if persisted_width_keys is not None else keys
        )
        if not persisted_keys.issubset(keys):
            raise ValueError(f"Invalid persisted-width columns for header {view_id}")
        self._all_persisted_width_keys = persisted_keys
        self._persisted_width_keys = persisted_keys
        self._default_widths = {
            key: self._header.sectionSize(logical) for logical, key in enumerate(keys)
        }
        self._default_sort_column = default_sort_column
        self._default_sort_order = default_sort_order
        self._restoring = False
        self._columns_updating = False
        self._model_reset_pending = False
        self._configure_capabilities()
        self.restore()
        self._connect()

    def _configure_capabilities(self) -> None:
        self._header.setSectionsMovable(self._movable)
        self._header.setSectionsClickable(self._sorting)
        self._header.setSortIndicatorShown(self._sorting)
        self._view.setSortingEnabled(self._sorting)

    def restore(self) -> None:
        layout = self._stored_layout()
        self._restoring = True
        try:
            for logical, key in enumerate(self._column_keys):
                width = layout.widths.get(key)
                if key not in self._persisted_width_keys:
                    continue
                if not isinstance(width, int) or not 30 <= width <= 2000:
                    width = self._default_widths[key]
                self._header.resizeSection(logical, width)
            if self._movable:
                saved_order = self._reconciled_saved_order(layout.order)
                target_order = tuple(
                    key for key in saved_order if key in self._column_keys
                )
                for visual, key in enumerate(target_order):
                    logical = self._column_keys.index(key)
                    current_visual = self._header.visualIndex(logical)
                    if current_visual != visual:
                        self._header.moveSection(current_visual, visual)
            if self._sorting:
                sort_key = (
                    layout.sort_column
                    if layout.sort_column in self._column_keys
                    else self._default_sort_column
                )
                if sort_key is not None:
                    order = (
                        QtCore.Qt.SortOrder.DescendingOrder
                        if layout.sort_column == sort_key and layout.sort_descending
                        else (
                            QtCore.Qt.SortOrder.AscendingOrder
                            if layout.sort_column == sort_key
                            else self._default_sort_order
                        )
                    )
                    self._view.sortByColumn(self._column_keys.index(sort_key), order)
            self._view.setSortingEnabled(self._sorting)
        finally:
            self._restoring = False

    def begin_columns_update(self, column_keys: Sequence[str]) -> None:
        if self._columns_updating:
            raise RuntimeError(f"Header columns already updating for {self._view_id}")
        keys = tuple(column_keys)
        if (
            any(not isinstance(key, str) or not key for key in keys)
            or len(set(keys)) != len(keys)
            or not set(keys).issubset(self._default_widths)
        ):
            raise ValueError(f"Invalid semantic columns for header {self._view_id}")
        self._columns_updating = True
        self._restoring = True
        self._view.setSortingEnabled(False)
        self._column_keys = keys
        self._persisted_width_keys = self._all_persisted_width_keys.intersection(keys)

    def end_columns_update(self) -> None:
        if len(self._column_keys) != self._view.columnCount():
            self._columns_updating = False
            self._restoring = False
            raise ValueError(f"Invalid semantic columns for header {self._view_id}")
        self._columns_updating = False
        self.restore()

    def _stored_layout(self) -> HeaderLayoutState:
        layout = self._workspace_state_model.state.header_layouts.get(
            self._view_id, HeaderLayoutState()
        )
        return self._layout_for_schema(layout)

    def _layout_for_schema(self, layout: HeaderLayoutState) -> HeaderLayoutState:
        if (
            self._movable
            and layout.order
            and not any(key in self._all_column_keys for key in layout.order)
        ):
            return HeaderLayoutState()
        return layout

    def _reconciled_saved_order(self, order: Sequence[str]) -> tuple[str, ...]:
        if not order:
            return self._all_column_keys
        retained = tuple(key for key in order if key in self._all_column_keys)
        if not retained:
            return self._all_column_keys
        reconciled = list(retained)
        for canonical_index, key in enumerate(self._all_column_keys):
            if key in reconciled:
                continue
            preceding_key = next(
                (
                    candidate
                    for candidate in reversed(self._all_column_keys[:canonical_index])
                    if candidate in reconciled
                ),
                None,
            )
            if preceding_key is not None:
                reconciled.insert(reconciled.index(preceding_key) + 1, key)
                continue
            following_key = next(
                (
                    candidate
                    for candidate in self._all_column_keys[canonical_index + 1 :]
                    if candidate in reconciled
                ),
                None,
            )
            if following_key is None:
                reconciled.append(key)
            else:
                reconciled.insert(reconciled.index(following_key), key)
        return tuple(reconciled)

    def _connect(self) -> None:
        self._header.sectionResized.connect(self._save)
        self._header.sectionMoved.connect(self._save)
        self._header.sortIndicatorChanged.connect(self._save)
        model = self._view.model()
        model.modelAboutToBeReset.connect(self._on_model_about_to_be_reset)
        model.modelReset.connect(self._on_model_reset)

    def _on_model_about_to_be_reset(self) -> None:
        self._model_reset_pending = True
        self._restoring = True

    def _on_model_reset(self) -> None:
        if not self._model_reset_pending:
            return
        self._model_reset_pending = False
        if not isValid(self._view):
            return
        if self._columns_updating:
            return
        if len(self._column_keys) != self._view.columnCount():
            self._restoring = False
            return
        self.restore()

    def _save(self, *_args) -> None:
        if self._restoring:
            return
        state = self._workspace_state_model.state
        existing_layout = state.header_layouts.get(self._view_id, HeaderLayoutState())
        stored_layout = self._layout_for_schema(existing_layout)
        widths = {
            key: width
            for key, width in stored_layout.widths.items()
            if key in self._all_persisted_width_keys
            and isinstance(width, int)
            and 30 <= width <= 2000
        }
        widths.update(
            {
                key: self._header.sectionSize(logical)
                for logical, key in enumerate(self._column_keys)
                if key in self._persisted_width_keys
            }
        )
        visible_order = [
            self._column_keys[self._header.logicalIndex(visual)]
            for visual in range(self._header.count())
        ]
        order = list(self._reconciled_saved_order(stored_layout.order))
        visible_keys = set(self._column_keys)
        visible_iter = iter(visible_order)
        order = [next(visible_iter) if key in visible_keys else key for key in order]
        sort_column = None
        sort_descending = False
        if self._sorting:
            logical = self._header.sortIndicatorSection()
            if 0 <= logical < len(self._column_keys):
                sort_column = self._column_keys[logical]
                sort_descending = (
                    self._header.sortIndicatorOrder()
                    == QtCore.Qt.SortOrder.DescendingOrder
                )
        updated_layout = HeaderLayoutState(
            widths=widths,
            order=order if self._movable else [],
            sort_column=sort_column,
            sort_descending=sort_descending,
        )
        if updated_layout == existing_layout:
            return
        state.header_layouts[self._view_id] = updated_layout
        try:
            self._workspace_state_model.update_state(state)
        except OSError:
            return
