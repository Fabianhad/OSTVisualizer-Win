import inspect
import json
import logging
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.ai_takeoff_dtos import (
    AI_TAKEOFF_COMMANDS,
    AiTakeoffRequestError,
)
from ost_visualizer.domain.entities.ai_changeset import (
    DATABASE_UNRESOLVED_MESSAGE,
    KIND_ELEMENTS,
    AiChangeset,
    ProposedCondition,
    ProposedTakeoff,
)
from ost_visualizer.application.services.ai_takeoff_read_service import (
    AiTakeoffReadService,
)
from ost_visualizer.application.dtos.ai_takeoff_dtos import SIDECAR_REBIND_REQUIRED
from ost_visualizer.application.services.ai_changeset_store import (
    AiChangesetProposals,
)
from ost_visualizer.application.services.ai_takeoff_sidecar_service import (
    SidecarContext,
)
from ost_visualizer.config.di_config import (
    _sidecar_level_uids,
    configure_application,
)
from ost_visualizer.domain.entities.ai_takeoff import (
    AiTakeoffSidecar,
    Level,
    SidecarFingerprint,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.infrastructure.logging.logger_factory import LoggerFactory
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.presentation.services.ai_takeoff_bridge import (
    TakeoffCommandBridge,
)
from ost_visualizer.presentation.managers.ui_access_manager import UIAccessManager
from ost_visualizer.presentation.services.ai_sidecar_rebind_prompt import (
    REBIND_PROMPT_TITLE,
)
from ost_visualizer.presentation.services.ai_undo_refusal_notice import (
    UNDO_REFUSED_TITLE,
)
from ost_visualizer.presentation.services.ai_takeoff_write_commands import (
    AiTakeoffWriteCommands,
)
from PySide6 import QtCore, QtWidgets


class MainWindowStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_main_window_constructs_from_configured_application(self):
        window = None
        controller = None
        with tempfile.TemporaryDirectory() as temp_dir, ExitStack() as stack:
            app_data_dir = Path(temp_dir)
            stack.enter_context(patch.object(Path, "home", return_value=app_data_dir))
            stack.enter_context(patch.object(LoggerFactory, "configure"))
            stack.enter_context(
                patch.object(
                    LoggerFactory,
                    "get_logger",
                    return_value=logging.getLogger("test.main_window.startup"),
                )
            )
            stack.enter_context(patch.object(QtCore.QTimer, "singleShot"))
            # Qt's offscreen platform exposes no installed system fonts. Font
            # resolution has its own tests and is unrelated to startup wiring.
            stack.enter_context(
                patch(
                    "ost_visualizer.presentation.utils.annotation_defaults."
                    "resolve_font_definition",
                    side_effect=lambda definition: definition,
                )
            )
            try:
                container = configure_application(log_dir=app_data_dir / "logs")
                controller = container.get("app_controller")
                window = MainWindow(controller)
                self.assertIs(window.app_controller, controller)
                self.assertIsInstance(window.ui_access_manager, UIAccessManager)
                self.assertIs(
                    window._workspace_state_model,
                    controller.get_service("workspace_state_model"),
                )
                self.assertIs(
                    window._annotation_view_manager._ui_access_manager,
                    window.ui_access_manager,
                )
                self.assertIs(
                    window._view_window_manager._ui_access_manager,
                    window.ui_access_manager,
                )
                left_splitter = window.get_left_splitter()
                self.assertEqual(left_splitter.minimumWidth(), 320)
                self.assertIs(left_splitter.widget(0), window._conditions_sidebar)
                self.assertIs(left_splitter.widget(1), window._bid_layers_sidebar)
                bridge = window._ai_takeoff_bridge
                self.assertIsInstance(bridge, TakeoffCommandBridge)
                self.assertEqual(bridge.commands, AI_TAKEOFF_COMMANDS)
                self.assertIsInstance(
                    controller.get_service("ai_takeoff_read_service"),
                    AiTakeoffReadService,
                )
                token_path = (
                    app_data_dir / ".ost_visualizer" / "ai_takeoff" / "session.token"
                )
                self.assertTrue(token_path.is_file())
                self.assertFalse(window._ai_takeoff_access_allowed())
                for name in (
                    "ai_changeset_store",
                    "ai_changeset_proposals",
                    "ai_takeoff_sidecar_service",
                    "ai_takeoff_proposal_service",
                    "ai_takeoff_audit_log",
                ):
                    self.assertIsNotNone(controller.get_service(name))
                self.assertIsNotNone(window._ai_approval)
                self.assertIsNotNone(window._ai_applier)
                gate = controller.get_service("ai_takeoff_apply_gate")
                self.assertEqual(
                    gate(str(app_data_dir / "job.mdb")), DATABASE_UNRESOLVED_MESSAGE
                )
                access = DatabaseDescriptor.for_access(str(app_data_dir / "job.mdb"))
                controller._database_descriptor_registry.register(access)
                self.assertEqual(gate(str(app_data_dir / "job.mdb")), "")
                self.assertEqual(
                    gate("sql:srv/unregistered"), DATABASE_UNRESOLVED_MESSAGE
                )
                sql = DatabaseDescriptor.for_sql_server(
                    SqlServerDatabaseLocation(
                        server="srv", database="ost", database_guid="g-1"
                    ),
                    schema_version=1,
                )
                controller._database_descriptor_registry.register(sql)
                self.assertIn("SQL Server", gate(sql.database_id))
                proposed = controller.get_service("ai_changeset_proposals").add(
                    AiChangeset(
                        uid="",
                        database_id=sql.database_id,
                        bid_uid="7",
                        bid_key="",
                        kind=KIND_ELEMENTS,
                        created_at=0.0,
                        conditions=(ProposedCondition("c1", "Slab", 8.0, 0.0),),
                        takeoffs=(
                            ProposedTakeoff(
                                "t1", "p1", "c1", (0.0, 0.0, 10.0, 0.0, 10.0, 10.0)
                            ),
                        ),
                    )
                )
                with self.assertRaises(AiTakeoffRequestError) as raised:
                    controller.get_service(
                        "ai_takeoff_proposal_service"
                    ).apply_changeset(proposed.uid)
                self.assertEqual(raised.exception.code, "sql_apply_unavailable")
                self.assertIn(
                    "Options > MCP Setup",
                    window._ai_takeoff_write_denial(SimpleNamespace(kind="elements")),
                )
                store = controller.get_service("ai_changeset_store")
                proposals = controller.get_service("ai_changeset_proposals")
                self.assertIsInstance(proposals, AiChangesetProposals)
                write = bridge._commands["apply_changeset"].__self__
                self.assertIsInstance(write, AiTakeoffWriteCommands)
                self.assertIs(write._proposals, proposals)
                self.assertIs(
                    write._proposal,
                    controller.get_service("ai_takeoff_proposal_service"),
                )
                self.assertEqual(
                    write._apply_requested, window._ai_approval.on_apply_requested
                )
                self.assertEqual(write._undo, window._ai_applier.undo)
                self.assertEqual(
                    window._ai_applier._undo_refused, window._ai_undo_notice.show
                )
                window._ai_undo_notice.show("AI: slab", "Edited since.", lambda: True)
                notices = [
                    box
                    for box in window.findChildren(QtWidgets.QMessageBox)
                    if box.windowTitle() == UNDO_REFUSED_TITLE
                ]
                self.assertEqual(len(notices), 1)
                self.assertTrue(notices[0].isVisible())
                window._ai_undo_notice.cleanup()
                self.assertFalse(notices[0].isVisible())
                self.assertFalse(any(value is store for value in vars(write).values()))
                self.assertEqual(
                    [
                        value
                        for value in vars(write).values()
                        if inspect.ismethod(value)
                        and value.__self__ is window._ai_approval
                    ],
                    [window._ai_approval.on_apply_requested],
                )
                self.assertEqual(bridge._audit, window._record_ai_tool)
                window._ai_approval.changeset_finished.emit("c-finished", "rejected")
                audit_file = (
                    app_data_dir
                    / ".ost_visualizer"
                    / "ai_takeoff"
                    / "audit"
                    / "unkeyed.jsonl"
                )
                decision = json.loads(
                    audit_file.read_text(encoding="utf-8").splitlines()[-1]
                )
                self.assertEqual(
                    (
                        decision["event"],
                        decision["changeset_id"],
                        decision["outcome"],
                    ),
                    ("decision", "c-finished", "rejected"),
                )
                sidecars = controller.get_service("ai_takeoff_sidecar_service")
                with patch.object(
                    sidecars,
                    "context",
                    return_value=SidecarContext(
                        SIDECAR_REBIND_REQUIRED, "0123456789abcdef0123456789abcdef"
                    ),
                ):
                    bridge.rebind_suggested.emit()
                prompts = [
                    box
                    for box in window.findChildren(QtWidgets.QMessageBox)
                    if box.windowTitle() == REBIND_PROMPT_TITLE
                ]
                self.assertEqual(len(prompts), 1)
                self.assertTrue(prompts[0].isVisible())
                window._ai_rebind_prompt.cleanup()
                window._ai_takeoff_bridge.cleanup()
                self.assertFalse(token_path.exists())
            finally:
                if window is not None:
                    window._workspace_state_coordinator.cleanup()
                    window.event_coordinator.cleanup()
                    window.handlers.ui_event.cleanup()
                    window.license_coordinator.cleanup()
                    window.ui_access_manager.cleanup()
                    window._mcp_context_bridge.cleanup()
                    window._ai_takeoff_bridge.cleanup()
                    window.hide()
                    window.deleteLater()
                if controller is not None:
                    controller.cleanup()
                if window is not None:
                    self.app.sendPostedEvents(window, QtCore.QEvent.Type.DeferredDelete)


class SidecarLevelUidTests(unittest.TestCase):
    def sidecars(self, status, levels=None):
        sidecar = None
        if levels is not None:
            sidecar = AiTakeoffSidecar(
                bid_key="0123456789abcdef0123456789abcdef",
                fingerprint=SidecarFingerprint("db", "Bid", 1, "a.pdf"),
                levels=tuple(Level(uid, uid, 120.0) for uid in levels),
            )
        context = SidecarContext(status, None, None, sidecar)
        return SimpleNamespace(context=lambda: context)

    def test_only_a_healthy_sidecar_contributes_level_uids(self):
        self.assertEqual(
            _sidecar_level_uids(self.sidecars("ok", ["L1", "L2"])), {"L1", "L2"}
        )
        self.assertEqual(_sidecar_level_uids(self.sidecars("ok", [])), set())
        self.assertEqual(_sidecar_level_uids(self.sidecars("ok")), set())
        for status in ("empty", SIDECAR_REBIND_REQUIRED, "corrupt"):
            with self.subTest(status=status):
                self.assertEqual(
                    _sidecar_level_uids(self.sidecars(status, ["L1"])), set()
                )
                self.assertEqual(_sidecar_level_uids(self.sidecars(status)), set())


if __name__ == "__main__":
    unittest.main()
