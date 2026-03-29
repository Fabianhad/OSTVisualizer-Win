class VisualizationOrchestrator:
    def __init__(self):
        self._visualization_service = None

    def set_visualization_service(self, svc) -> None:
        self._visualization_service = svc

    def close_realtime_visualization(self) -> None:
        if self._visualization_service:
            self._visualization_service.close_realtime_visualization()

    def cleanup(self) -> None:
        if self._visualization_service:
            self._visualization_service.cleanup()
