import html
import logging
import webbrowser
from PySide6 import QtCore, QtWidgets
from ...application.interfaces.i_window_icon_provider import IWindowIconProvider
from ...domain.entities.version_info import VersionInfo
from ..config import (
    COMPACT_SPACING,
    NO_MARGINS,
    RELAXED_MARGINS,
    RELAXED_SPACING,
    UPDATE_WINDOW_HEIGHT,
    UPDATE_WINDOW_WIDTH,
)
from ..utils.theme import get_dialog_header_font
from ..utils.windows import remove_minimize_maximize
from ..texts import (
    UPDATE_DIALOG_BUTTON_NO_LATER,
    UPDATE_DIALOG_BUTTON_YES_DOWNLOAD,
    UPDATE_DIALOG_LABEL_A_HREF_VIEW_FULL_RELEASE_NOTES,
    UPDATE_DIALOG_LABEL_A_NEW_VERSION_OF_OST_VISUALIZER,
    UPDATE_DIALOG_LABEL_CHANGELOG,
    UPDATE_DIALOG_LABEL_UPDATE_AVAILABLE,
    UPDATE_DIALOG_TITLE_UPDATE_AVAILABLE,
)

logger = logging.getLogger(__name__)
_CHANGELOG_SECTION_ORDER = (
    ("added", "Added"),
    ("changed", "Changed"),
    ("fixed", "Fixed"),
)


class UpdateDialog(QtWidgets.QDialog):
    def __init__(
        self,
        icon_provider: IWindowIconProvider,
        parent,
        version_info: VersionInfo,
    ):
        super().__init__(parent)
        self.icon_provider = icon_provider
        self.version_info = version_info
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle(UPDATE_DIALOG_TITLE_UPDATE_AVAILABLE)
        self.setModal(True)
        remove_minimize_maximize(self)
        self.icon_provider.set_window_icon(self)
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(*RELAXED_MARGINS)
        main_layout.setSpacing(RELAXED_SPACING)
        title = QtWidgets.QLabel(UPDATE_DIALOG_LABEL_UPDATE_AVAILABLE, self)
        title.setFont(get_dialog_header_font())
        main_layout.addWidget(title)
        message = QtWidgets.QLabel(self)
        message.setWordWrap(True)
        message.setText(
            UPDATE_DIALOG_LABEL_A_NEW_VERSION_OF_OST_VISUALIZER.format(
                your_version=self.version_info.your_version,
                current_version=self.version_info.current_version,
                release_date_text=self._release_date_text(),
            )
        )
        main_layout.addWidget(message)
        changelog = self._build_changelog_widget()
        if changelog:
            main_layout.addWidget(changelog, stretch=1)
        link = self._build_release_link()
        if link:
            main_layout.addWidget(link)
        button_box = QtWidgets.QDialogButtonBox(self)
        download_button = button_box.addButton(
            UPDATE_DIALOG_BUTTON_YES_DOWNLOAD,
            QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole,
        )
        later_button = button_box.addButton(
            UPDATE_DIALOG_BUTTON_NO_LATER,
            QtWidgets.QDialogButtonBox.ButtonRole.RejectRole,
        )
        download_button.clicked.connect(self._on_yes)
        later_button.clicked.connect(self.reject)
        main_layout.addWidget(button_box)
        self.setFixedSize(UPDATE_WINDOW_WIDTH, UPDATE_WINDOW_HEIGHT)

    def _on_yes(self) -> None:
        download_url = self.version_info.download_url
        if download_url:
            webbrowser.open(download_url)
        else:
            logger.warning("No download URL available")
        self.accept()

    def show_dialog(self) -> None:
        self.exec()

    def _release_date_text(self) -> str:
        release_date = self.version_info.release_date
        if not release_date:
            return ""
        return f" ({release_date[:10]})"

    def _build_changelog_widget(self):
        changelog_html = self._build_changelog_html()
        if not changelog_html:
            return None
        container = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(*NO_MARGINS)
        layout.setSpacing(COMPACT_SPACING)
        heading = QtWidgets.QLabel(UPDATE_DIALOG_LABEL_CHANGELOG, container)
        heading.setFont(get_dialog_header_font())
        layout.addWidget(heading)
        changelog_label = QtWidgets.QLabel(changelog_html, container)
        changelog_label.setTextFormat(QtCore.Qt.TextFormat.RichText)
        changelog_label.setWordWrap(True)
        changelog_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        changelog_label.setMargin(COMPACT_SPACING)
        scroll_area = QtWidgets.QScrollArea(container)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        scroll_area.setWidget(changelog_label)
        layout.addWidget(scroll_area, stretch=1)
        return container

    def _build_release_link(self):
        link_url = self.version_info.release_url or self.version_info.release_notes_url
        if link_url:
            return QtWidgets.QLabel(
                UPDATE_DIALOG_LABEL_A_HREF_VIEW_FULL_RELEASE_NOTES.format(
                    escape=html.escape(link_url, quote=True)
                ),
                self,
                openExternalLinks=True,
            )
        return None

    def _build_changelog_html(self) -> str:
        changelog = self.version_info.changelog or {}
        parts = []
        for key, title in _CHANGELOG_SECTION_ORDER:
            items = changelog.get(key) or []
            if not items:
                continue
            parts.append(f"<p><strong>{title}</strong></p><ul>")
            for item in items:
                parts.append(f"<li>{html.escape(item)}</li>")
            parts.append("</ul>")
        return "".join(parts)
