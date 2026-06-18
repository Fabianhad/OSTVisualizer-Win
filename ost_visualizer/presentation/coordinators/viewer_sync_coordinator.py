from typing import List, Optional
from ..managers.ui_access_manager import Feature


class ViewerSyncCoordinator:
    def __init__(
        self,
        ui_state_manager,
        ui_access_manager,
        color_service,
        project_data,
        visualization_service,
    ):
        self._ui_state = ui_state_manager
        self._access = ui_access_manager
        self._color_service = color_service
        self._project_data = project_data
        self._visualization_service = visualization_service
        self.plan_view = None
        self.opengl_viewer = None

    def clear_viewer(self) -> None:
        if self.opengl_viewer:
            self.opengl_viewer.clear_scene()
        self._clear_plan_view()

    def _clear_plan_view(self) -> None:
        if self.plan_view:
            self.plan_view.clear()

    def update_plan_view_for_active(self) -> None:
        uid = self._ui_state.active_page_uid
        if not uid:
            pages = self._project_data.get_selected_page_uids()
            uid = pages[0] if pages else None
        if uid:
            self.update_plan_view(uid)
        else:
            self._clear_plan_view()

    def update_plan_view(self, page_uid: Optional[str]) -> None:
        if not self.plan_view or not page_uid:
            self._clear_plan_view()
            return
        page = self._project_data.get_page(page_uid)
        if not page:
            self._clear_plan_view()
            return
        conditions = self._project_data.get_bid_conditions()
        page_takeoffs = self._project_data.get_page_takeoffs(page_uid)
        page_annotations = self._project_data.get_page_annotations(page_uid)
        visible_annotations = [a for a in page_annotations if a.visible]
        color_mode = self._ui_state.state.color_mode
        grayscale_enabled = self._ui_state.state.grayscale_enabled
        place_uid = self._ui_state.place_condition_uid
        extra = {place_uid} if place_uid else None
        _, color_map = self._color_service.get_color_mapping(
            conditions,
            page_takeoffs,
            color_mode,
            grayscale_enabled,
            extra,
        )
        bid_ref = self._ui_state.get_selected_bid_ref()
        page_area_selections = self._project_data.get_page_area_selections()
        hidden_layer_uids = self._project_data.get_hidden_layer_uids()
        if (
            self.plan_view.current_page_uid == page_uid
            and self.plan_view.refresh_current_page_overlays(
                page=page,
                takeoffs=page_takeoffs,
                conditions=conditions,
                color_map=color_map,
                bid_ref=bid_ref,
                annotations=visible_annotations,
                page_area_selections=page_area_selections,
                hidden_layer_uids=hidden_layer_uids,
            )
        ):
            if bid_ref:
                bid = self._project_data.get_bid(bid_ref)
                if bid:
                    self.plan_view.set_snap_settings(
                        bid.takeoff_increments,
                        bid.measure_base,
                    )
            return
        self.plan_view.load_page(
            page=page,
            takeoffs=page_takeoffs,
            conditions=conditions,
            color_map=color_map,
            bid_ref=bid_ref,
            annotations=visible_annotations,
            page_area_selections=page_area_selections,
            hidden_layer_uids=hidden_layer_uids,
        )
        if bid_ref:
            bid = self._project_data.get_bid(bid_ref)
            if bid:
                self.plan_view.set_snap_settings(
                    bid.takeoff_increments,
                    bid.measure_base,
                )

    def update_viewers(self, page_uids: List[str]) -> None:
        if not page_uids and self.opengl_viewer:
            self.opengl_viewer.clear_scene()
        self._visualization_service.refresh_mesh_view(page_uids)

    def update_license_visualization_state(self) -> None:
        if not self._access.is_allowed(Feature.VIEW_3D):
            if self.opengl_viewer:
                self.opengl_viewer.clear_scene()
        else:
            selected_pages = self._project_data.get_selected_page_uids()
            self._visualization_service.refresh_mesh_view(selected_pages)
        if self._access.is_allowed(Feature.VIEW_2D):
            self.update_plan_view_for_active()
        else:
            self._clear_plan_view()

    def cleanup(self) -> None:
        self.plan_view = None
        self.opengl_viewer = None
        self._ui_state = None
        self._access = None
        self._color_service = None
        self._project_data = None
        self._visualization_service = None
