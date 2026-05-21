# OST Visualizer

Open your [On-Screen Takeoff](https://www.oncenter.com/products/on-screen-takeoff/) projects and review them in 2D plan view. Upgrade to visualize in 3D, edit conditions, and export to DXF, PDF, and OBJ.

Built for estimators and construction teams who work with OST project files daily.

**[Download](https://fabianhad.com/ost3d/download)** | **[Commercial License](https://fabianhad.com/ost3d/download)** | **[Release Notes](https://fabianhad.com/ost3d/release-notes)**

[![Version](https://img.shields.io/badge/version-1.2.3-blue)](https://fabianhad.com/ost3d/download)
[![License: Elastic-2.0](https://img.shields.io/badge/license-Elastic--2.0-blue)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows%2064--bit-lightgrey)]()
[![Build](https://github.com/Fabianhad/OSTVisualizer-Win/actions/workflows/architecture.yml/badge.svg)](https://github.com/Fabianhad/OSTVisualizer-Win/actions/workflows/architecture.yml)

## Screenshots

<!-- Replace with actual screenshots:
![3D View](docs/screenshots/3d-view.png)
*Takeoff conditions visualized in 3D with transparent overlays.*

![Plan View](docs/screenshots/plan-view.png)
*Annotations and takeoffs overlaid on PDF plan sheets.*
-->

*Screenshots coming soon.*

## Features

- **2D Plan View** -- Interactive view with annotations overlaid on project pages, including detached Annotation and View windows
- **PDF Plan Sheets** -- View PDF drawings at any scale
- **Multi-database** -- Open and browse multiple project files at the same time
- **Bid Organization** -- Full project hierarchy for navigating bids and conditions
- **3D Visualization** -- See takeoff geometry rendered in full 3D with transparent overlays *(Commercial)*
- **Import/Export** -- Move data between OST, OSP, PDF, DXF, OBJ, and FBX formats *(Commercial)*
- **Condition Management** -- Create, edit, duplicate, and organize conditions across bids *(Commercial)*
- **Realtime Sync** -- Detects when On-Screen Takeoff is active and picks up changes automatically ([free companion tool](https://fabianhad.com/ost3d/download))

## Demo

<!-- Replace with demo link:
[![Watch the demo](docs/screenshots/demo-thumbnail.png)](https://youtube.com/watch?v=...)
-->

*Demo video coming soon.*

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
| Local AI Context | Model Context Protocol via stdlib stdio helper (optional, Python 3.10+) |

## Local MCP Server

OST Visualizer includes an optional read-only local MCP server for MCP-compatible
clients such as Claude Desktop and Cursor. It runs as a separate stdio process,
does not start inside the Qt UI thread, and exposes only registered `.mdb`
database context from OST Visualizer's local checked-file settings.
It does not support `--database` or other arbitrary database path overrides.

The MCP server exposes project, bid, page, PDF metadata, condition, takeoff,
condition summary, selected-page summary, selected-takeoff summary, search,
quantity-summary, page-context, duplicate-condition, zero-quantity, unplaced
takeoff, and lightweight scope-gap review tools. Broad result sets use explicit
limits and include status/metadata such as returned count and truncation state.
It does not expose shell execution, arbitrary SQL, arbitrary file reads, PDF
text extraction, rendering, exports, or database mutation. CSV export is
intentionally deferred until the app has a polished CSV export system. Page text
is also deferred unless a safe app-owned extraction path is added later.
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
separate MCP dependency install or extra MCP setup step.
Compatibility has been smoke-tested with the official Python MCP client for
initialize, tools, resources, templates, and prompts. Production builds include a
separate lightweight MCP helper executable. Use `Tools > MCP Setup...` in the
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

The desktop client lives inside the main server repository:

- Client root: `projects/ost3d/client`
- App package: `projects/ost3d/client/ost_visualizer`
- Entry point: `projects/ost3d/client/Visualizer.py`
- MCP entry point: `projects/ost3d/client/McpServer.py`
- Server license API: `projects/ost3d/routes/api.py` and `projects/ost3d/utils/validation.py`

Run client setup, development, architecture, and build commands from `projects/ost3d/client`.

## License Client

The desktop client calls the server license API at `/validate`, `/activate`, and `/deactivate`. It verifies RSA-signed activate/validate responses, stores the local license cache as `license_cache.json`, and supports offline grace only when the server/network response is unusable and the cached license is still valid.

Normal license denials, such as not found, revoked, expired, activation limit reached, or HWID-related failures, are handled separately from server/network/contract failures.

Current minimal API contract:

```text
POST /validate request: {"license_key": "...", "hwid": "..."}
POST /validate success: {"valid": true, "expiry_date": "...", "signature": "..."}
POST /activate request: {"license_key": "...", "hwid": "..."}
POST /activate success: {"success": true, "expiry_date": "...", "signature": "..."}
POST /deactivate request: {"license_key": "...", "hwid": "..."}
POST /deactivate success: {"success": true, "message": "..."}
Failure: {"error": "...", "error_code": 1001}
```

The server may also return `activation_count`, `max_activations`, and `active_hwids` as server/admin metadata. The desktop client currently ignores those fields for authorization. Service entitlements are not implemented; do not use `max_activations` to restrict desktop/web service access.

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

Architecture rules, conventions, and development setup are documented in [CLAUDE.md](CLAUDE.md). Read it before making changes. Architecture checks run automatically via pre-commit hook and CI:

```bash
python tools/check_architecture.py
```

Focused license validation commands:

```bash
python3 -m py_compile ../routes/api.py ../utils/validation.py
python3 -m py_compile ost_visualizer/application/use_cases/license/*.py
python3 -m py_compile ost_visualizer/infrastructure/external/license_api_client.py
```

Tests may require the client virtual environment with PySide6 and native-extension prerequisites installed.

## License

[Elastic License 2.0](LICENSE)
