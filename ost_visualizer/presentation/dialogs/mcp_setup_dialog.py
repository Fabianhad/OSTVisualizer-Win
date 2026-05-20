from pathlib import Path
from typing import Optional
from PySide6 import QtCore, QtWidgets
from ...application.interfaces.i_window_icon_provider import IWindowIconProvider
from ..config import (
    DIALOG_BUTTON_WIDTH,
    MCP_SETUP_WINDOW_HEIGHT,
    MCP_SETUP_WINDOW_WIDTH,
    RELAXED_MARGINS,
    RELAXED_SPACING,
)
from ..utils.theme import get_dialog_header_font
from ..utils.windows import remove_minimize_maximize
from .mcp_setup_config import (
    build_claude_desktop_config,
    build_codex_mcp_add_command,
    default_file_state_path,
    default_mcp_helper_path,
)


class McpSetupDialog(QtWidgets.QDialog):
    def __init__(
        self,
        icon_provider: IWindowIconProvider,
        parent=None,
        helper_path: Optional[Path] = None,
    ):
        super().__init__(parent)
        self.icon_provider = icon_provider
        self.helper_path = (
            Path(helper_path) if helper_path else default_mcp_helper_path()
        )
        self.file_state_path = default_file_state_path()
        self.status_label = None
        self.claude_config_edit = None
        self.codex_command_edit = None
        self.copy_claude_button = None
        self.copy_codex_button = None
        self.close_button = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle("MCP Setup")
        self.setModal(True)
        remove_minimize_maximize(self)
        self.resize(MCP_SETUP_WINDOW_WIDTH, MCP_SETUP_WINDOW_HEIGHT)
        self.setMinimumSize(MCP_SETUP_WINDOW_WIDTH, MCP_SETUP_WINDOW_HEIGHT)
        self.icon_provider.set_window_icon(self)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(*RELAXED_MARGINS)
        layout.setSpacing(RELAXED_SPACING)
        header = QtWidgets.QLabel("Configure MCP clients", self)
        header.setFont(get_dialog_header_font())
        layout.addWidget(header)
        self.status_label = QtWidgets.QLabel(self._status_text(), self)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addWidget(self._section_label("Claude Desktop / Cursor config"))
        self.claude_config_edit = self._read_only_text_edit(
            build_claude_desktop_config(self.helper_path),
            min_height=165,
        )
        layout.addWidget(self.claude_config_edit)
        self.copy_claude_button = QtWidgets.QPushButton("Copy Config", self)
        self.copy_claude_button.clicked.connect(self._copy_claude_config)
        layout.addWidget(
            self.copy_claude_button,
            alignment=QtCore.Qt.AlignmentFlag.AlignRight,
        )
        layout.addWidget(self._section_label("Codex command"))
        self.codex_command_edit = self._read_only_text_edit(
            build_codex_mcp_add_command(self.helper_path),
            min_height=70,
        )
        layout.addWidget(self.codex_command_edit)
        button_row = QtWidgets.QHBoxLayout()
        self.copy_codex_button = QtWidgets.QPushButton("Copy Command", self)
        self.copy_codex_button.clicked.connect(self._copy_codex_command)
        button_row.addWidget(self.copy_codex_button)
        button_row.addStretch(1)
        self.close_button = QtWidgets.QPushButton("Close", self)
        self.close_button.setMinimumWidth(DIALOG_BUTTON_WIDTH)
        self.close_button.clicked.connect(self.accept)
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)

    def _status_text(self) -> str:
        helper_status = "found" if self.helper_path.exists() else "not found"
        file_state_status = "found" if self.file_state_path.exists() else "not found"
        return (
            f"MCP helper: {self.helper_path} ({helper_status})\n"
            f"Database source: {self.file_state_path} ({file_state_status})\n"
            "MCP uses checked OST Visualizer databases only. It does not accept "
            "custom database paths."
        )

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

    def _copy_claude_config(self) -> None:
        self._copy_to_clipboard(self.claude_config_edit.toPlainText())

    def _copy_codex_command(self) -> None:
        self._copy_to_clipboard(self.codex_command_edit.toPlainText())

    def _copy_to_clipboard(self, text: str) -> None:
        QtWidgets.QApplication.clipboard().setText(text)
        self.status_label.setText(self._status_text() + "\nCopied to clipboard.")

    def cleanup(self) -> None:
        for button in (
            self.copy_claude_button,
            self.copy_codex_button,
            self.close_button,
        ):
            if button:
                try:
                    button.clicked.disconnect()
                except (TypeError, RuntimeError):
                    pass
        self.status_label = None
        self.claude_config_edit = None
        self.codex_command_edit = None
        self.copy_claude_button = None
        self.copy_codex_button = None
        self.close_button = None
        self.helper_path = None
        self.file_state_path = None
        self.icon_provider = None

    def closeEvent(self, event) -> None:
        self.cleanup()
        event.accept()
