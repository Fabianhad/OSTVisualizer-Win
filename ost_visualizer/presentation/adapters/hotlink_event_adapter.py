from ...application.dtos.hotlink_dto import HotlinkDto
from ...application.events.app_events import AppEvents
from ...application.interfaces.i_shutdown_aware import IShutdownAware


class HotlinkEventAdapter(IShutdownAware):
    def __init__(self, event_bus):
        self.event_bus = event_bus
        self._plan_view = None

    def set_plan_view(self, plan_view) -> None:
        self._plan_view = plan_view
        plan_view.hotlink_clicked.connect(self._on_hotlink_clicked)

    def shutdown(self) -> None:
        if self._plan_view:
            try:
                self._plan_view.hotlink_clicked.disconnect(self._on_hotlink_clicked)
            except Exception:
                pass
            self._plan_view = None

    def _on_hotlink_clicked(self, info: HotlinkDto) -> None:
        self.event_bus.publish(
            AppEvents.HOTLINK_CLICKED,
            hotlink_uid=info.uid,
            bid_page_uid=info.bid_page_uid,
            target_view_uid=info.target_view_uid,
            position_x=info.center_x,
            position_y=info.center_y,
        )
