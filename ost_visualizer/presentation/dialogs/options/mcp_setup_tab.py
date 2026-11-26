from pathlib import Path
from typing import Optional
from PySide6 import QtCore, QtWidgets
from ...config import NO_MARGINS, RELAXED_MARGINS, RELAXED_SPACING
from ...utils.mcp_setup_config import (
    TAKEOFF_MCP_SERVER_NAME,
    build_claude_desktop_config,
    build_codex_config_toml,
    build_codex_mcp_add_command,
    default_file_state_path,
    default_mcp_helper_path,
    default_takeoff_helper_path,
)
from ...utils.theme import get_dialog_header_font
from ...texts import (
    MCP_SETUP_TAB_BUTTON_COPY_AI_TAKEOFF_JSON,
    MCP_SETUP_TAB_BUTTON_COPY_CODEX_TOML,
    MCP_SETUP_TAB_BUTTON_COPY_SETUP_COMMAND,
    MCP_SETUP_TAB_BUTTON_COPY_SETUP_JSON,
    MCP_SETUP_TAB_LABEL_AI_TAKEOFF_FOR_CLAUDE_DESKTOP_OR,
    MCP_SETUP_TAB_LABEL_AI_TAKEOFF_PREVIEW,
    MCP_SETUP_TAB_LABEL_CLAUDE_DESKTOP_OR_CURSOR,
    MCP_SETUP_TAB_LABEL_CODEX,
    MCP_SETUP_TAB_LABEL_CODEX_CLI_COMMAND,
    MCP_SETUP_TAB_LABEL_CODEX_CONFIG_TOML,
    MCP_SETUP_TAB_LABEL_CODEX_CONNECTS_TO_THE_LOCAL_STDIO,
    MCP_SETUP_TAB_LABEL_CONNECT_AI_TOOLS,
    MCP_SETUP_TAB_LABEL_COPY_ONE_SETUP_OPTION_BELOW_THEN,
    MCP_SETUP_TAB_LABEL_LETS_AN_AI_TOOL_READ_SHEETS,
    MCP_SETUP_TAB_OPTION_ALLOW_AI_TAKEOFF_TOOLS_WHILE_OST,
    MCP_SETUP_TAB_STATUS_COPIED_TO_CLIPBOARD,
    MCP_SETUP_TAB_STATUS_MCP_HELPER_IS_NOT_INSTALLED_YET,
    MCP_SETUP_TAB_STATUS_READY_AFTER_YOU_CHECK_AT_LEAST,
    MCP_SETUP_TAB_STATUS_READY_TO_CONNECT_CHECKED_OST_VISUALIZER,
)


class McpSetupTab(QtWidgets.QWidget):
    def __init__(
        self,
        parent=None,
        helper_path: Optional[Path] = None,
        takeoff_helper_path: Optional[Path] = None,
    ):
        super().__init__(parent)
        self.helper_path = (
            Path(helper_path) if helper_path else default_mcp_helper_path()
        )
        self.takeoff_helper_path = (
            Path(takeoff_helper_path)
            if takeoff_helper_path
            else default_takeoff_helper_path()
        )
        self.ai_takeoff_check = None
        self.takeoff_config_edit = None
        self.copy_takeoff_button = None
        self.file_state_path = default_file_state_path()
        self.status_label = None
        self.claude_config_edit = None
        self.codex_config_edit = None
        self.codex_command_edit = None
        self.copy_claude_button = None
        self.copy_codex_config_button = None
        self.copy_codex_button = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer_layout = QtWidgets.QVBoxLayout(self)
        outer_layout.setContentsMargins(*NO_MARGINS)
        scroll_area = QtWidgets.QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        content = QtWidgets.QWidget(scroll_area)
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(*RELAXED_MARGINS)
        layout.setSpacing(RELAXED_SPACING)
        header = QtWidgets.QLabel(MCP_SETUP_TAB_LABEL_CONNECT_AI_TOOLS, self)
        header.setFont(get_dialog_header_font())
        layout.addWidget(header)
        summary = QtWidgets.QLabel(
            MCP_SETUP_TAB_LABEL_COPY_ONE_SETUP_OPTION_BELOW_THEN,
            self,
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        self.status_label = QtWidgets.QLabel(self._status_text(), self)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.claude_config_edit, self.copy_claude_button = self._add_copy_block(
            layout,
            MCP_SETUP_TAB_LABEL_CLAUDE_DESKTOP_OR_CURSOR,
            build_claude_desktop_config(self.helper_path),
            135,
            MCP_SETUP_TAB_BUTTON_COPY_SETUP_JSON,
            self._copy_claude_config,
        )
        layout.addWidget(self._section_label(MCP_SETUP_TAB_LABEL_CODEX))
        codex_summary = QtWidgets.QLabel(
            MCP_SETUP_TAB_LABEL_CODEX_CONNECTS_TO_THE_LOCAL_STDIO,
            self,
        )
        codex_summary.setWordWrap(True)
        layout.addWidget(codex_summary)
        (
            self.codex_config_edit,
            self.copy_codex_config_button,
        ) = self._add_copy_block(
            layout,
            MCP_SETUP_TAB_LABEL_CODEX_CONFIG_TOML,
            build_codex_config_toml(self.helper_path),
            80,
            MCP_SETUP_TAB_BUTTON_COPY_CODEX_TOML,
            self._copy_codex_config,
        )
        self.codex_command_edit, self.copy_codex_button = self._add_copy_block(
            layout,
            MCP_SETUP_TAB_LABEL_CODEX_CLI_COMMAND,
            build_codex_mcp_add_command(self.helper_path),
            55,
            MCP_SETUP_TAB_BUTTON_COPY_SETUP_COMMAND,
            self._copy_codex_command,
        )
        layout.addWidget(self._section_label(MCP_SETUP_TAB_LABEL_AI_TAKEOFF_PREVIEW))
        takeoff_summary = QtWidgets.QLabel(
            MCP_SETUP_TAB_LABEL_LETS_AN_AI_TOOL_READ_SHEETS,
            self,
        )
        takeoff_summary.setWordWrap(True)
        layout.addWidget(takeoff_summary)
        self.ai_takeoff_check = QtWidgets.QCheckBox(
            MCP_SETUP_TAB_OPTION_ALLOW_AI_TAKEOFF_TOOLS_WHILE_OST, self
        )
        layout.addWidget(self.ai_takeoff_check)
        self.takeoff_config_edit, self.copy_takeoff_button = self._add_copy_block(
            layout,
            MCP_SETUP_TAB_LABEL_AI_TAKEOFF_FOR_CLAUDE_DESKTOP_OR,
            build_claude_desktop_config(
                self.takeoff_helper_path, TAKEOFF_MCP_SERVER_NAME
            ),
            135,
            MCP_SETUP_TAB_BUTTON_COPY_AI_TAKEOFF_JSON,
            self._copy_takeoff_config,
        )
        layout.addStretch(1)
        scroll_area.setWidget(content)
        outer_layout.addWidget(scroll_area)

    def refresh_status(self) -> None:
        if self.status_label is not None:
            self.status_label.setText(self._status_text())

    def _status_text(self, feedback: str = "") -> str:
        helper_ready = self.helper_path.exists()
        file_state_ready = self.file_state_path.exists()
        if helper_ready and file_state_ready:
            status = MCP_SETUP_TAB_STATUS_READY_TO_CONNECT_CHECKED_OST_VISUALIZER
        elif helper_ready:
            status = MCP_SETUP_TAB_STATUS_READY_AFTER_YOU_CHECK_AT_LEAST
        else:
            status = MCP_SETUP_TAB_STATUS_MCP_HELPER_IS_NOT_INSTALLED_YET
        if feedback:
            return f"{status}\n{feedback}"
        return status

    def _section_label(self, text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text, self)
        label.setStyleSheet("font-weight: 600;")
        return label

    def _read_only_text_edit(
        self,
        text: str,
        min_height: int,
    ) -> QtWidgets.QPlainTextEdit:
        edit = QtWidgets.QPlainTextEdit(self)
        edit.setReadOnly(True)
        edit.setPlainText(text)
        edit.setMinimumHeight(min_height)
        edit.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        return edit

    def _add_copy_block(
        self,
        layout: QtWidgets.QVBoxLayout,
        label: str,
        text: str,
        min_height: int,
        button_text: str,
        copy_slot,
    ) -> tuple[QtWidgets.QPlainTextEdit, QtWidgets.QPushButton]:
        layout.addWidget(self._section_label(label))
        edit = self._read_only_text_edit(text, min_height=min_height)
        layout.addWidget(edit)
        button = QtWidgets.QPushButton(button_text, self)
        button.clicked.connect(copy_slot)
        layout.addWidget(button, alignment=QtCore.Qt.AlignmentFlag.AlignRight)
        return edit, button

    def _copy_claude_config(self) -> None:
        self._copy_to_clipboard(self.claude_config_edit.toPlainText())

    def _copy_codex_config(self) -> None:
        self._copy_to_clipboard(self.codex_config_edit.toPlainText())

    def _copy_codex_command(self) -> None:
        self._copy_to_clipboard(self.codex_command_edit.toPlainText())

    def _copy_takeoff_config(self) -> None:
        self._copy_to_clipboard(self.takeoff_config_edit.toPlainText())

    def _copy_to_clipboard(self, text: str) -> None:
        QtWidgets.QApplication.clipboard().setText(text)
        self.status_label.setText(
            self._status_text(MCP_SETUP_TAB_STATUS_COPIED_TO_CLIPBOARD)
        )

    def cleanup(self) -> None:
        for button in (
            self.copy_claude_button,
            self.copy_codex_config_button,
            self.copy_codex_button,
            self.copy_takeoff_button,
        ):
            if button:
                try:
                    button.clicked.disconnect()
                except (TypeError, RuntimeError):
                    pass
        self.status_label = None
        self.claude_config_edit = None
        self.codex_config_edit = None
        self.codex_command_edit = None
        self.copy_claude_button = None
        self.copy_codex_config_button = None
        self.copy_codex_button = None
        self.ai_takeoff_check = None
        self.takeoff_config_edit = None
        self.copy_takeoff_button = None
        self.helper_path = None
        self.takeoff_helper_path = None
        self.file_state_path = None
