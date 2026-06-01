import json
import logging
from typing import Optional
from PySide6 import QtCore
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from ...application.dtos.mcp_context_dtos import MCP_BRIDGE_SERVER_NAME
from ...domain.entities.identity_refs import BidRef

logger = logging.getLogger(__name__)


class McpContextBridge(QtCore.QObject):
    def __init__(
        self,
        main_window,
        ui_state_manager,
        project_data_service,
        plan_view,
        parent: Optional[QtCore.QObject] = None,
    ):
        super().__init__(parent)
        self._main_window = main_window
        self._ui_state = ui_state_manager
        self._project_data = project_data_service
        self._plan_view = plan_view
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)

    def start(self) -> None:
        self._server.removeServer(MCP_BRIDGE_SERVER_NAME)
        if not self._server.listen(MCP_BRIDGE_SERVER_NAME):
            logger.warning(
                "Failed to start MCP context bridge: %s",
                self._server.errorString(),
            )

    def cleanup(self) -> None:
        if self._server is not None:
            try:
                self._server.newConnection.disconnect(self._on_new_connection)
            except (TypeError, RuntimeError):
                pass
            self._server.close()
            self._server.removeServer(MCP_BRIDGE_SERVER_NAME)
        for socket in self.findChildren(QLocalSocket):
            try:
                socket.readyRead.disconnect()
            except (TypeError, RuntimeError):
                pass
            try:
                socket.disconnected.disconnect()
            except (TypeError, RuntimeError):
                pass
            socket.abort()
            socket.deleteLater()
        self._main_window = None
        self._ui_state = None
        self._project_data = None
        self._plan_view = None
        self._server = None

    def _on_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.setParent(self)
            socket.readyRead.connect(lambda socket=socket: self._handle_request(socket))
            socket.disconnected.connect(socket.deleteLater)

    def _handle_request(self, socket: QLocalSocket) -> None:
        request = bytes(socket.readAll()).decode("utf-8", errors="replace").strip()
        try:
            payload = json.loads(request) if request else {}
            if payload.get("command") != "get_context":
                response = self._error("unsupported_command")
            else:
                response = {
                    "success": True,
                    "data": self._build_snapshot(),
                }
        except (TypeError, ValueError, RuntimeError) as exc:
            response = self._error(str(exc))
        socket.write(json.dumps(response).encode("utf-8"))
        socket.flush()
        socket.disconnectFromServer()

    def _build_snapshot(self) -> dict:
        selected_bid_ref = self._ui_state.get_selected_bid_ref()
        current_bid_ref = self._project_data.get_current_bid_ref()
        selected_file_path = self._ui_state.selected_file_path
        active_page_uid = self._ui_state.active_page_uid
        active_view = self._main_window.get_active_takeoff_view()
        return {
            "source": "live_app",
            "active_tab_index": self._main_window.tab_widget.currentIndex(),
            "active_tab_name": self._main_window.tab_widget.tabText(
                self._main_window.tab_widget.currentIndex()
            ),
            "active_view": active_view,
            "is_takeoff_tab_active": self._main_window.is_takeoff_tab_active(),
            "selected_file_path": selected_file_path,
            "database_selected": self._ui_state.is_database_selected(),
            "selected_project_uid": self._ui_state.selected_project_uid,
            "selected_project_uids": self._ui_state.selected_project_uids,
            "selected_bid_ref": self._bid_ref_to_dict(selected_bid_ref),
            "selected_bid_refs": [
                self._bid_ref_to_dict(ref)
                for ref in self._ui_state.get_selected_bid_refs()
            ],
            "current_bid_ref": self._bid_ref_to_dict(current_bid_ref),
            "current_bid_locked": self._project_data.is_current_bid_locked(),
            "selected_page_uids": self._ui_state.selected_page_uids,
            "mesh_page_uids": self._ui_state.selected_page_uids,
            "active_page_uid": active_page_uid,
            "highlighted_condition_uids": sorted(
                self._ui_state.highlighted_condition_uids
            ),
            "place_condition_uid": self._ui_state.place_condition_uid,
            "place_condition_uids": self._ui_state.place_condition_uids,
            "selected_area_uid": self._ui_state.selected_area_uid,
            "selected_takeoff_uids": self._selected_takeoff_uids(active_view),
        }

    def _selected_takeoff_uids(self, active_view: str) -> list:
        readers = (
            (self._embedded_3d_selected_takeoff_uids, self._plan_selected_takeoff_uids)
            if active_view == "3d"
            else (
                self._plan_selected_takeoff_uids,
                self._embedded_3d_selected_takeoff_uids,
            )
        )
        for reader in readers:
            uids = reader()
            if uids:
                return uids
        mesh_window = self._main_window.get_mesh_window()
        if mesh_window:
            return self._clean_uid_list(mesh_window.get_selected_takeoff_uids())
        return []

    def _plan_selected_takeoff_uids(self) -> list:
        return self._clean_uid_list(self._plan_view.get_selected_takeoff_uids())

    def _embedded_3d_selected_takeoff_uids(self) -> list:
        viewer = self._main_window.opengl_viewer
        if viewer is None:
            return []
        return self._clean_uid_list(viewer.get_selected_takeoff_uids())

    @staticmethod
    def _clean_uid_list(raw_uids) -> list:
        result = []
        for uid in raw_uids or []:
            text = str(uid)
            if text and text not in result:
                result.append(text)
        return result

    @staticmethod
    def _bid_ref_to_dict(ref: Optional[BidRef]) -> Optional[dict]:
        if ref is None:
            return None
        return {
            "file_path": ref.file_path,
            "bid_uid": ref.bid_uid,
        }

    @staticmethod
    def _error(message: str) -> dict:
        return {
            "success": False,
            "error": str(message),
        }
