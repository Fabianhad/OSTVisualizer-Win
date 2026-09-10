from pathlib import Path
from typing import Optional
from PySide6 import QtCore, QtWidgets
from ...config import NO_MARGINS, RELAXED_MARGINS, RELAXED_SPACING
from ...utils.mcp_setup_config import (
    build_claude_desktop_config,
    build_codex_config_toml,
    build_codex_mcp_add_command,
    default_file_state_path,
    default_mcp_helper_path,
)
from ...utils.theme import get_dialog_header_font


class McpSetupTab(QtWidgets.QWidget):
    def __init__(
        self,
        parent=None,
        helper_path: Optional[Path] = None,
    ):
        super().__init__(parent)
        self.helper_path = (
            Path(helper_path) if helper_path else default_mcp_helper_path()
        )
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
        header = QtWidgets.QLabel("Connect AI tools", self)
        header.setFont(get_dialog_header_font())
        layout.addWidget(header)
        summary = QtWidgets.QLabel(
            "Copy one setup option below, then restart that AI tool.",
            self,
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        self.status_label = QtWidgets.QLabel(self._status_text(), self)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.claude_config_edit, self.copy_claude_button = self._add_copy_block(
            layout,
            "Claude Desktop or Cursor",
            build_claude_desktop_config(self.helper_path),
            135,
            "Copy Setup JSON",
            self._copy_claude_config,
        )
        layout.addWidget(self._section_label("Codex"))
        codex_summary = QtWidgets.QLabel(
            "Codex connects to the local stdio helper and sees checked files "
            "or live context from OST Visualizer.",
            self,
        )
        codex_summary.setWordWrap(True)
        layout.addWidget(codex_summary)
        (
            self.codex_config_edit,
            self.copy_codex_config_button,
        ) = self._add_copy_block(
            layout,
            "Codex config.toml",
            build_codex_config_toml(self.helper_path),
            80,
            "Copy Codex TOML",
            self._copy_codex_config,
        )
        self.codex_command_edit, self.copy_codex_button = self._add_copy_block(
            layout,
            "Codex CLI command",
            build_codex_mcp_add_command(self.helper_path),
            55,
            "Copy Setup Command",
            self._copy_codex_command,
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
            status = "Ready to connect checked OST Visualizer files."
        elif helper_ready:
            status = "Ready after you check at least one OST Visualizer file."
        else:
            status = "MCP helper is not installed yet."
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

    def _copy_to_clipboard(self, text: str) -> None:
        QtWidgets.QApplication.clipboard().setText(text)
        self.status_label.setText(self._status_text("Copied to clipboard."))

    def cleanup(self) -> None:
        for button in (
            self.copy_claude_button,
            self.copy_codex_config_button,
            self.copy_codex_button,
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
        self.helper_path = None
        self.file_state_path = None
