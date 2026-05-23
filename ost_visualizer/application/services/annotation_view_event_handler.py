import logging
from ..events.app_events import AppEvents
from ..interfaces.i_shutdown_aware import IShutdownAware
from ..interfaces.i_startable import IStartable


class AnnotationViewEventHandler(IShutdownAware, IStartable):
    def __init__(self, event_bus, use_case_factory, logger: logging.Logger):
        self._event_bus = event_bus
        self._use_case_factory = use_case_factory
        self.logger = logger
        self._subscribed = False
        self._use_case = None

    def _get_use_case(self):
        if self._use_case is None:
            self._use_case = self._use_case_factory()
        return self._use_case

    def start(self) -> None:
        if self._subscribed:
            return
        self._event_bus.subscribe(AppEvents.HOTLINK_CLICKED, self._on_hotlink_clicked)
        self._subscribed = True

    def shutdown(self) -> None:
        if not self._subscribed:
            return
        self._event_bus.unsubscribe(AppEvents.HOTLINK_CLICKED, self._on_hotlink_clicked)
        self._subscribed = False

    def _on_hotlink_clicked(
        self,
        hotlink_uid: str = "",
        bid_page_uid: str = "",
        target_view_uid: str = None,
        position_x: float = 0,
        position_y: float = 0,
        **kwargs
    ) -> None:
        try:
            event = AppEvents.HOTLINK_CLICKED(
                hotlink_uid=hotlink_uid,
                bid_page_uid=bid_page_uid,
                target_view_uid=target_view_uid,
                position_x=position_x,
                position_y=position_y,
            )
            self._get_use_case().execute_from_hotlink(event)
        except Exception:
            self.logger.exception("Error handling HOTLINK_CLICKED")
