import hmac
import json
import logging
import os
import secrets
import threading
from pathlib import Path
from typing import Callable, Optional, Union
from PySide6 import QtCore
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from shiboken6 import isValid
from ...application.dtos.ai_takeoff_dtos import (
    AI_TAKEOFF_BRIDGE_SERVER_NAME,
    AI_TAKEOFF_COMMAND_ARGUMENTS,
    AI_TAKEOFF_COMMANDS,
    AI_TAKEOFF_DIR_NAME,
    AI_TAKEOFF_SESSION_TOKEN_FILE_NAME,
    APP_DATA_DIR_NAME,
    COMMAND_GET_QUANTITIES,
    COMMAND_LIST_ASSUMPTIONS,
    COMMAND_LIST_LEVELS,
    COMMAND_LIST_SEGMENTS,
    COMMAND_LIST_SHEETS,
    COMMAND_LIST_TEXT,
    COMMAND_RENDER_SHEET,
    ERROR_BUSY,
    ERROR_FEATURE_DENIED,
    ERROR_INVALID_ARGUMENT,
    ERROR_UNAUTHORIZED,
    ERROR_UNEXPECTED,
    ERROR_UNKNOWN_COMMAND,
    SIDECAR_REBIND_REQUIRED,
    AiTakeoffRequestError,
    error_result,
    ok_result,
)
from .ai_takeoff_crop_renderer import render_crop_png
from .ai_takeoff_write_commands import DeferredReply

logger = logging.getLogger(__name__)
MAX_REQUEST_BYTES = 64 * 1024
MAX_CONCURRENT_WORKERS = 2
MAX_OPEN_CONNECTIONS = 8
IDLE_REQUEST_TIMEOUT_MS = 10000
_BUSY_MESSAGE = (
    "OST Visualizer is busy with other AI takeoff requests. Try again shortly."
)


def ai_takeoff_session_token_path() -> Path:
    return (
        Path.home()
        / APP_DATA_DIR_NAME
        / AI_TAKEOFF_DIR_NAME
        / AI_TAKEOFF_SESSION_TOKEN_FILE_NAME
    )


class TakeoffCommandBridge(QtCore.QObject):
    _job_finished = QtCore.Signal(object, object)
    rebind_suggested = QtCore.Signal()

    def __init__(
        self,
        read_service,
        pdf_source,
        access_allowed: Callable[[], bool],
        token_path: Path,
        server_name: str = AI_TAKEOFF_BRIDGE_SERVER_NAME,
        token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32),
        parent: Optional[QtCore.QObject] = None,
        max_workers: int = MAX_CONCURRENT_WORKERS,
        max_connections: int = MAX_OPEN_CONNECTIONS,
        idle_timeout_ms: int = IDLE_REQUEST_TIMEOUT_MS,
        write_commands=None,
        audit: Callable[
            [str, dict, str], None
        ] = lambda _tool, _arguments, _outcome: None,
    ):
        super().__init__(parent)
        self._read_service = read_service
        self._pdf_source = pdf_source
        self._access_allowed = access_allowed
        self._token_path = Path(token_path)
        self._server_name = server_name
        self._token_factory = token_factory
        self._token: Optional[str] = None
        self._buffers: dict = {}
        self._open_sockets: set = set()
        self._active_workers = 0
        self._max_workers = max(1, int(max_workers))
        self._max_connections = max(1, int(max_connections))
        self._idle_timeout_ms = max(1, int(idle_timeout_ms))
        self._server: Optional[QLocalServer] = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._on_new_connection)
        self._job_finished.connect(self._finish)
        self._commands = {
            COMMAND_LIST_SHEETS: self._list_sheets,
            COMMAND_RENDER_SHEET: self._render_sheet,
            COMMAND_LIST_TEXT: self._list_text,
            COMMAND_LIST_SEGMENTS: self._list_segments,
            COMMAND_GET_QUANTITIES: self._get_quantities,
            COMMAND_LIST_LEVELS: self._list_levels,
            COMMAND_LIST_ASSUMPTIONS: self._list_assumptions,
        }
        if write_commands is not None:
            self._commands.update(write_commands.handlers())
        self._audit = audit

    @property
    def commands(self) -> tuple:
        return tuple(name for name in AI_TAKEOFF_COMMANDS if name in self._commands)

    def start(self) -> bool:
        if self._server is None:
            return False
        self._server.removeServer(self._server_name)
        if not self._server.listen(self._server_name):
            logger.warning("Failed to start the AI takeoff bridge")
            return False
        try:
            self._token = self._token_factory()
            _write_token(self._token_path, self._token)
        except OSError as exc:
            logger.warning(
                "Failed to write the AI takeoff session token: %s", type(exc).__name__
            )
            self._server.close()
            self._token = None
            return False
        return True

    def cleanup(self) -> None:
        if self._server is not None:
            try:
                self._server.newConnection.disconnect(self._on_new_connection)
            except (TypeError, RuntimeError):
                pass
            self._server.close()
            self._server.removeServer(self._server_name)
        for socket in self.findChildren(QLocalSocket):
            socket.abort()
            socket.deleteLater()
        self._buffers.clear()
        self._open_sockets.clear()
        self._remove_own_token()
        self._token = None
        self._server = None
        self._read_service = None
        self._pdf_source = None

    def _remove_own_token(self) -> None:
        if self._token is None:
            return
        try:
            if self._token_path.read_text(encoding="utf-8").strip() == self._token:
                self._token_path.unlink()
        except (OSError, UnicodeError):
            pass

    def _on_new_connection(self) -> None:
        while self._server is not None and self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.setParent(self)
            if len(self._open_sockets) >= self._max_connections:
                socket.disconnected.connect(socket.deleteLater)
                self._respond(socket, error_result(ERROR_BUSY, _BUSY_MESSAGE))
                continue
            self._open_sockets.add(id(socket))
            self._buffers[id(socket)] = bytearray()
            socket.readyRead.connect(lambda socket=socket: self._on_ready_read(socket))
            socket.disconnected.connect(lambda socket=socket: self._forget(socket))
            QtCore.QTimer.singleShot(
                self._idle_timeout_ms,
                socket,
                lambda socket=socket: self._on_idle(socket),
            )

    def _forget(self, socket: QLocalSocket) -> None:
        self._buffers.pop(id(socket), None)
        self._open_sockets.discard(id(socket))
        socket.deleteLater()

    def _on_idle(self, socket: QLocalSocket) -> None:
        if self._buffers.pop(id(socket), None) is None or not isValid(socket):
            return
        self._respond(
            socket,
            error_result(
                ERROR_INVALID_ARGUMENT, "No complete request was received in time."
            ),
        )

    def _on_ready_read(self, socket: QLocalSocket) -> None:
        buffer = self._buffers.get(id(socket))
        if buffer is None:
            return
        buffer.extend(bytes(socket.readAll()))
        if len(buffer) > MAX_REQUEST_BYTES:
            self._buffers.pop(id(socket), None)
            self._respond(
                socket, error_result(ERROR_INVALID_ARGUMENT, "Request too large.")
            )
            return
        if b"\n" not in buffer:
            return
        self._buffers.pop(id(socket), None)
        line = bytes(buffer).split(b"\n", 1)[0]
        self._handle(socket, line)

    def _handle(self, socket: QLocalSocket, line: bytes) -> None:
        try:
            request = json.loads(line.decode("utf-8"))
        except (UnicodeError, ValueError, RecursionError):
            self._respond(
                socket, error_result(ERROR_INVALID_ARGUMENT, "Malformed request.")
            )
            return
        if not isinstance(request, dict):
            self._respond(
                socket, error_result(ERROR_INVALID_ARGUMENT, "Malformed request.")
            )
            return
        token = request.get("token")
        if (
            self._token is None
            or not isinstance(token, str)
            or not hmac.compare_digest(
                token.encode("utf-8", "surrogatepass"),
                self._token.encode("utf-8", "surrogatepass"),
            )
        ):
            self._respond(
                socket, error_result(ERROR_UNAUTHORIZED, "Session token rejected.")
            )
            return
        command = request.get("command")
        handler = self._commands.get(command) if isinstance(command, str) else None
        if handler is None:
            self._respond(
                socket,
                error_result(ERROR_UNKNOWN_COMMAND, "This command is not available."),
            )
            return
        arguments = request.get("arguments")
        if arguments is None:
            arguments = {}
        if (
            not isinstance(arguments, dict)
            or not set(arguments) <= AI_TAKEOFF_COMMAND_ARGUMENTS[command]
        ):
            self._respond(
                socket,
                error_result(ERROR_INVALID_ARGUMENT, "Unknown or malformed arguments."),
            )
            return
        if not self._access_allowed():
            self._respond(
                socket,
                error_result(
                    ERROR_FEATURE_DENIED,
                    "AI takeoff is not enabled or not available for the open bid.",
                ),
            )
            return
        try:
            worker_job = handler(arguments)
        except AiTakeoffRequestError as exc:
            self._reply(socket, command, arguments, error_result(exc.code, exc.message))
            return
        except Exception as exc:
            logger.exception("AI takeoff command failed: %s", type(exc).__name__)
            self._reply(
                socket,
                command,
                arguments,
                error_result(ERROR_UNEXPECTED, "The command failed."),
            )
            return
        if isinstance(worker_job, dict):
            self._reply(socket, command, arguments, worker_job)
            return
        if isinstance(worker_job, DeferredReply):
            worker_job.attach(
                lambda result, socket=socket: self._finish_deferred(
                    socket, command, arguments, result
                )
            )
            return
        if self._active_workers >= self._max_workers:
            self._reply(
                socket, command, arguments, error_result(ERROR_BUSY, _BUSY_MESSAGE)
            )
            return
        self._active_workers += 1
        threading.Thread(
            target=self._run_worker_job,
            args=(socket, (command, arguments), worker_job),
            name="AiTakeoffBridgeWorker",
            daemon=True,
        ).start()

    def _reply(
        self, socket: QLocalSocket, command: str, arguments: dict, result: dict
    ) -> None:
        self._respond(socket, result)
        try:
            self._audit(command, arguments, str(result.get("status", "")))
        except Exception as exc:
            logger.warning("AI takeoff audit failed: %s", type(exc).__name__)
        data = result.get("data")
        if (
            isinstance(data, dict)
            and data.get("sidecar_status") == SIDECAR_REBIND_REQUIRED
        ):
            self.rebind_suggested.emit()

    def _finish_deferred(
        self, socket, command: str, arguments: dict, result: dict
    ) -> None:
        if self._server is None or not isValid(socket):
            return
        self._reply(socket, command, arguments, result)

    def _run_worker_job(
        self, socket: QLocalSocket, request: tuple, job: Callable[[], dict]
    ) -> None:
        try:
            result = job()
        except AiTakeoffRequestError as exc:
            result = error_result(exc.code, exc.message)
        except Exception as exc:
            logger.exception("AI takeoff worker job failed: %s", type(exc).__name__)
            result = error_result(ERROR_UNEXPECTED, "The command failed.")
        try:
            self._job_finished.emit(socket, (request, result))
        except RuntimeError:
            logger.info("AI takeoff bridge closed before a command finished")

    def _finish(self, socket, outcome: tuple) -> None:
        self._active_workers = max(0, self._active_workers - 1)
        if self._server is None or not isValid(socket):
            return
        (command, arguments), result = outcome
        self._reply(socket, command, arguments, result)

    @staticmethod
    def _respond(socket: QLocalSocket, result: dict) -> None:
        payload = json.dumps(result).encode("ascii") + b"\n"
        socket.write(payload)
        socket.flush()
        socket.disconnectFromServer()

    def _list_sheets(self, arguments: dict) -> dict:
        return self._read_service.list_sheets(
            bid_uid=arguments.get("bid_uid"),
            cursor=arguments.get("cursor"),
            limit=arguments.get("limit"),
        )

    def _get_quantities(self, arguments: dict) -> dict:
        return self._read_service.get_quantities(
            bid_uid=arguments.get("bid_uid"),
            group_by=arguments.get("group_by", "condition"),
        )

    def _list_levels(self, arguments: dict) -> dict:
        return self._read_service.list_levels(bid_uid=arguments.get("bid_uid"))

    def _list_assumptions(self, arguments: dict) -> dict:
        return self._read_service.list_assumptions(
            bid_uid=arguments.get("bid_uid"), status=arguments.get("status")
        )

    def _list_text(self, arguments: dict) -> Callable[[], dict]:
        snapshot = self._read_service.page_snapshot(arguments.get("page_uid"))
        service = self._read_service
        return lambda: service.list_text(
            snapshot,
            bbox_pts=arguments.get("bbox_pts"),
            query=arguments.get("query"),
            cursor=arguments.get("cursor"),
            limit=arguments.get("limit"),
        )

    def _list_segments(self, arguments: dict) -> Callable[[], dict]:
        snapshot = self._read_service.page_snapshot(arguments.get("page_uid"))
        service = self._read_service
        return lambda: service.list_segments(
            snapshot,
            bbox_pts=arguments.get("bbox_pts"),
            cursor=arguments.get("cursor"),
            limit=arguments.get("limit"),
        )

    def _render_sheet(self, arguments: dict) -> Union[dict, Callable[[], dict]]:
        snapshot = self._read_service.page_snapshot(arguments.get("page_uid"))
        overlay_status = self._read_service.overlay_status(arguments.get("overlay_ids"))
        if not snapshot.is_pdf:
            return ok_result(
                {
                    "page_uid": snapshot.uid,
                    "image": None,
                    "overlay_status": overlay_status,
                },
                "not_pdf",
            )
        plan = self._read_service.plan_crop(
            snapshot, crop_pts=arguments.get("crop_pts"), dpi=arguments.get("dpi")
        )
        pdf_source = self._pdf_source

        def render() -> dict:
            data = render_crop_png(pdf_source, plan)
            data["overlay_status"] = overlay_status
            status = "ok" if data["image"] is not None else data["render_status"]
            return ok_result(data, status)

        return render


def _write_token(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(token, encoding="utf-8")
    os.replace(temporary, path)
