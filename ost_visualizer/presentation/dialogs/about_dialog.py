from datetime import datetime
from PySide6 import QtCore, QtWidgets
from ...application.interfaces.i_window_icon_provider import IWindowIconProvider
from ...application.services.update_check_service import UpdateCheckService
from ..config import (
    ABOUT_WINDOW_HEIGHT,
    ABOUT_WINDOW_WIDTH,
    DIALOG_BUTTON_WIDTH,
    RELAXED_MARGINS,
    RELAXED_SPACING,
)
from ..utils.theme import get_dialog_header_font
from ..utils.windows import remove_minimize_maximize

_ABOUT_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <style>
      body {
        font-family: "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont,
          sans-serif;
        margin: 0;
        padding: 0;
        line-height: 1.5;
      }
      main {
        padding: 0;
      }
      h1 {
        font-size: 1.4rem;
        margin-bottom: 0.4rem;
      }
      h2 {
        font-size: 1.1rem;
        margin-top: 1.4rem;
        margin-bottom: 0.4rem;
      }
      p {
        margin: 0.3rem 0;
      }
      ul {
        margin: 0.4rem 0 0.4rem 1.2rem;
      }
      a {
        color: inherit;
      }
      .meta {
        font-size: 0.9rem;
      }
      table {
        font-size: 0.85rem;
        border-collapse: collapse;
        width: 100%;
      }
      th {
        text-align: left;
        border-bottom: 1px solid #555;
        padding: 3px 4px;
      }
      td {
        padding: 3px 4px;
      }
      tr.alt {
        background-color: rgba(255, 255, 255, 0.04);
      }
    </style>
  </head>
  <body>
    <main>
      <h1>OST Visualizer</h1>
      <p class="meta">Version {{version}}</p>
      <p>View and analyze On-Screen Takeoff projects in 2D and 3D.</p>
      <p class="meta"><a href="https://fabianhad.com/ost3d/">fabianhad.com/ost3d</a></p>
      <h2>Highlights</h2>
      <ul>
        <li>Interactive 2D plan view with annotations overlaid on PDF sheets</li>
        <li>Open and browse multiple project files at the same time</li>
        <li>3D visualization, editing, and export (with commercial license)</li>
      </ul>
      <h2>Credits</h2>
      <p>Created by {{creator}}</p>
      <p>&copy; {{year}} {{creator}}. Licensed under
        <a href="https://www.elastic.co/licensing/elastic-license">Elastic License 2.0</a>.</p>
      <h2>Third-Party Libraries</h2>
      <table cellpadding="2" cellspacing="0">
        <tr>
          <th>Library</th><th>License</th><th>Author / Notice</th>
        </tr>
        <tr>
          <td>PySide6 (Qt for Python)</td>
          <td>LGPL v3</td>
          <td>&copy; The Qt Company Ltd.</td>
        </tr>
        <tr class="alt">
          <td>pyodbc</td>
          <td>MIT</td>
          <td>&copy; Michael Kleehammer</td>
        </tr>
        <tr>
          <td>nanobind</td>
          <td>BSD 3-Clause</td>
          <td>&copy; Wenzel Jakob</td>
        </tr>
        <tr class="alt">
          <td>Manifold</td>
          <td>Apache 2.0</td>
          <td>&copy; The Manifold Authors</td>
        </tr>
        <tr>
          <td>GLM</td>
          <td>MIT</td>
          <td>&copy; G-Truc Creation</td>
        </tr>
        <tr class="alt">
          <td>PDFium</td>
          <td>Apache 2.0</td>
          <td>&copy; The Chromium Authors</td>
        </tr>
        <tr>
          <td>QPDF</td>
          <td>Apache 2.0</td>
          <td>&copy; Jay Berkenbilt</td>
        </tr>
        <tr class="alt">
          <td>GLAD</td>
          <td>MIT</td>
          <td>&copy; David Herberth</td>
        </tr>
        <tr>
          <td>earcut.hpp</td>
          <td>ISC</td>
          <td>&copy; Mapbox</td>
        </tr>
        <tr class="alt">
          <td>Clipper2</td>
          <td>Boost 1.0</td>
          <td>&copy; Angus Johnson</td>
        </tr>
        <tr>
          <td>Nuitka</td>
          <td>Apache 2.0</td>
          <td>&copy; Kay Hayen</td>
        </tr>
      </table>
    </main>
  </body>
</html>"""


class AboutDialog(QtWidgets.QDialog):
    def __init__(
        self,
        icon_provider: IWindowIconProvider,
        parent=None,
        creator_name: str = "Fabian",
    ):
        super().__init__(parent)
        self.icon_provider = icon_provider
        self.creator_name = creator_name
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle("About OST Visualizer")
        self.setModal(True)
        remove_minimize_maximize(self)
        self.resize(ABOUT_WINDOW_WIDTH, ABOUT_WINDOW_HEIGHT)
        self.setMinimumSize(ABOUT_WINDOW_WIDTH, ABOUT_WINDOW_HEIGHT)
        self.icon_provider.set_window_icon(self)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(*RELAXED_MARGINS)
        layout.setSpacing(RELAXED_SPACING)
        intro = QtWidgets.QLabel("Learn more about OST Visualizer", self)
        intro.setFont(get_dialog_header_font())
        layout.addWidget(intro)
        self.content_view = QtWidgets.QTextBrowser(self)
        self.content_view.setReadOnly(True)
        self.content_view.setOpenExternalLinks(True)
        self.content_view.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.content_view.setHtml(self._load_html_content())
        layout.addWidget(self.content_view, stretch=1)
        self.close_button = QtWidgets.QPushButton("Close", self)
        self.close_button.setMinimumWidth(DIALOG_BUTTON_WIDTH)
        self.close_button.clicked.connect(self.accept)
        layout.addWidget(
            self.close_button, alignment=QtCore.Qt.AlignmentFlag.AlignRight
        )

    def _load_html_content(self) -> str:
        return (
            _ABOUT_HTML_TEMPLATE.replace(
                "{{version}}", UpdateCheckService.CURRENT_VERSION
            )
            .replace("{{creator}}", self.creator_name)
            .replace("{{year}}", str(datetime.now().year))
        )

    def cleanup(self) -> None:
        if self.close_button:
            try:
                self.close_button.clicked.disconnect()
            except (TypeError, RuntimeError):
                pass
            self.close_button = None
        if self.content_view:
            self.content_view.clear()
            self.content_view = None
        self.creator_name = None
        self.icon_provider = None

    def closeEvent(self, event) -> None:
        self.cleanup()
        event.accept()
