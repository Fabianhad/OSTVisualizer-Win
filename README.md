# OST Visualizer

Open your [On-Screen Takeoff](https://www.oncenter.com/products/on-screen-takeoff/) projects and review them in 2D plan view. Upgrade to visualize in 3D, edit conditions, and export to DXF, PDF, and OBJ.

Built for estimators and construction teams who work with OST project files daily.

**[Download](https://fabianhad.com/ost3d/download)** | **[Commercial License](https://fabianhad.com/ost3d/download)** | **[Release Notes](https://fabianhad.com/ost3d/release-notes)**

[![Version](https://img.shields.io/badge/version-1.2.3-blue)](https://fabianhad.com/ost3d/download)
[![License: Elastic-2.0](https://img.shields.io/badge/license-Elastic--2.0-blue)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows%2064--bit-lightgrey)]()
[![Build](https://github.com/Fabianhad/OSTVisualizer-Win/actions/workflows/architecture.yml/badge.svg)](https://github.com/Fabianhad/OSTVisualizer-Win/actions/workflows/architecture.yml)

## Features

- **2D Plan View** -- Interactive view with annotations overlaid on project pages, including detached Annotation and View windows
- **PDF Plan Sheets** -- View PDF drawings at any scale
- **Multi-database** -- Open and browse multiple project files at the same time
- **Bid Organization** -- Full project hierarchy for navigating bids and conditions
- **3D Visualization** -- See takeoff geometry rendered in full 3D with transparent overlays *(Commercial)*
- **Import/Export** -- Move data between OST, OSP, PDF, DXF, OBJ, and FBX formats *(Commercial)*
- **Condition Management** -- Create, edit, duplicate, and organize conditions across bids *(Commercial)*
- **Realtime Sync** -- Detects when On-Screen Takeoff is active and picks up changes automatically ([free companion tool](https://fabianhad.com/ost3d/download))

## Download

Download the latest installer from the [download page](https://fabianhad.com/ost3d/download):

- **`ost3dvisualizer-1.2.3-64.msi`** -- Windows 64-bit installer (Windows 10+)

> A [commercial license](https://fabianhad.com/ost3d/download) is required for production use. See [Licensing](#licensing).

## Licensing

This software is source-available under the [Elastic License 2.0](LICENSE).

| | Free (Viewer) | Commercial License |
|---|---|---|
| Open and browse projects | Included | Included |
| 2D plan view (read-only) | Included | Included |
| 3D visualization | -- | Included |
| Edit takeoffs, conditions, bids | -- | Included |
| Import/Export (PDF, DXF, OBJ, FBX) | -- | Included |
| Production use | -- | Included |
| Support | Community | Email ([fabian@fabianhad.com](mailto:fabian@fabianhad.com)) |
| Price | Free | [Get a license](https://fabianhad.com/ost3d/download) |

### What You Can Do

- **View source code** -- Read, study, and learn from the codebase
- **Contribute** -- Submit pull requests and improvements
- **Non-production use** -- Run the software for development, testing, and personal evaluation
- **Production use with a license** -- Use all features in commercial environments with a valid license key

### What You Cannot Do

- **Circumvent the license key** -- You may not disable, remove, or bypass license key functionality
- **Offer as a hosted service** -- You may not provide the software to third parties as a managed service
- **Remove notices** -- You may not alter or remove licensing or copyright notices

### Commercial License

A commercial license unlocks 3D visualization, editing, and import/export for production use. One license key per machine.

**[Get a commercial license](https://fabianhad.com/ost3d/download)**

For licensing questions, contact [fabian@fabianhad.com](mailto:fabian@fabianhad.com).

## Who Is This For

- **Estimators** reviewing On-Screen Takeoff projects visually before bidding
- **Project managers** inspecting bid scope across multiple databases
- **Construction teams** working with takeoff data in 2D and 3D

## Tech Stack

| Component | Technology |
|---|---|
| UI | PySide6 (Qt 6.10.2) |
| Language | Python 3.8+, C++17 |
| 3D Rendering | OpenGL via custom C++ renderer |
| Geometry | Manifold, Earcut |
| PDF | PDFium, QPDF |
| Database | Microsoft Access (.mdb) via pyodbc |
| Build | Nuitka, CMake |
| C++ Bindings | nanobind v2.4.0 (13 extension modules) |
| Local AI Context | Model Context Protocol via stdlib stdio helper |

## Local MCP Server

OST Visualizer includes an optional read-only local MCP server for MCP-compatible
clients such as Claude Desktop, Cursor, and Codex. It runs as a separate stdio
process and exposes only checked `.mdb` databases from
`~/.ost_visualizer/file_state.json`. The desktop GUI does not start the stdio
server; it only provides a live-context bridge when the app is running.

The MCP server exposes project, bid, page, PDF metadata, condition, takeoff,
condition summary, selected-page summary, selected-takeoff summary, search,
quantity-summary, page-context, duplicate-condition, zero-quantity, unplaced
takeoff, and lightweight scope-gap review tools. Broad result sets use explicit
limits and include status/metadata such as returned count and truncation state.
It does not support `--database`, arbitrary database paths, shell execution,
arbitrary SQL, arbitrary file reads, PDF rendering/text extraction, OCR, page
text, exports, CSV, or database mutation.
When the desktop app is running, `get_current_context` also includes a live
read-only UI snapshot through a local app bridge, including active tab/view,
selected bid/page/conditions, and selected takeoff UIDs.

Developers can run the source checkout MCP helper directly:

```powershell
.\venv\Scripts\python.exe -m ost_visualizer.mcp_server.main
```

Claude Desktop / Cursor style configuration:

```json
{
  "mcpServers": {
    "ost-visualizer": {
      "command": "C:\\path\\to\\OSTVisualizerLicense\\venv\\Scripts\\python.exe",
      "args": ["-m", "ost_visualizer.mcp_server.main"],
      "env": {
        "PYTHONPATH": "C:\\path\\to\\OSTVisualizerLicense"
      }
    }
  }
}
```

The MCP server uses an internal stdlib stdio implementation. There is no
separate MCP dependency install or extra MCP setup step. Production builds
include a lightweight `ostv-mcp.exe` helper. Use `Tools > MCP Setup...` in the
desktop app to copy client configuration for the packaged helper. The setup
dialog only generates and copies text; it does not edit Claude Desktop, Cursor,
or Codex configuration files. After adding the configuration, restart or reload
your MCP client so it launches the helper:

```json
{
  "mcpServers": {
    "ost-visualizer": {
      "command": "C:\\Program Files\\OST Visualizer\\ostv-mcp.exe",
      "args": []
    }
  }
}
```

Codex production setup uses the helper directly:

```powershell
codex mcp add ost-visualizer -- 'C:\Program Files\OST Visualizer\ostv-mcp.exe'
```

If a client reports that the server is unavailable, confirm that
`C:\Program Files\OST Visualizer\ostv-mcp.exe` exists and that at least one
database is checked in OST Visualizer. The checked database list is stored in
`~/.ost_visualizer/file_state.json`; unchecked or missing databases are not
visible to MCP clients.

## Repository Layout

This repository is the desktop client checkout:

- Client root: repository root
- App package: `ost_visualizer`
- Entry point: `Visualizer.py`
- MCP entry point: `McpServer.py`
- License server implementation: outside this client checkout

Run client setup, development, architecture, and build commands from the repository root.

## Building from Source

Requires Python 3.8+, Visual Studio 2022 (MSVC x64), CMake 3.20+, and Qt 6.10.2.

```powershell
.\scripts\setup.ps1          # Create venv, install Python dependencies
.\scripts\setup-cpp.ps1      # Download vendor libs, build C++ extensions
.\scripts\run.ps1             # Run the application
```

For release builds:

```powershell
New-Item -ItemType Directory -Force .secrets
# Copy your license_public_key.pem into .secrets\license_public_key.pem first.
.\scripts\build.ps1           # Nuitka standalone builds -> dist_visualizer/ and dist_mcp/
.\build-msi.ps1               # Package into MSI installer
```

## Contributing

Contributions are welcome under the [Elastic License 2.0](LICENSE). By submitting a pull request, you agree that your contribution will be licensed under the same terms.

Architecture rules, conventions, and development setup are documented in [AGENTS.md](AGENTS.md). Read it before making changes. Architecture checks run automatically via pre-commit hook and CI:

```bash
python tools/check_architecture.py
```

Tests may require the client virtual environment with PySide6 and native-extension prerequisites installed.

## License

[Elastic License 2.0](LICENSE)
