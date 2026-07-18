# OST Visualizer

Open your [On-Screen Takeoff](https://www.oncenter.com/products/on-screen-takeoff/) projects and review them in Projects, Takeoff, and Summary views. Upgrade to visualize in 3D, edit conditions, and export to OST/OSP, HTML, PDF, CSV, DXF, OBJ, and FBX.

Built for estimators and construction teams who work with OST project files daily.

**[Download](https://fabianhad.com/ost3d/download)** | **[Commercial License](https://fabianhad.com/ost3d/download)** | **[Release Notes](https://fabianhad.com/ost3d/release-notes)**

[![Version](https://img.shields.io/badge/version-1.2.4.3-blue)](https://fabianhad.com/ost3d/download)
[![License: Elastic-2.0](https://img.shields.io/badge/license-Elastic--2.0-blue)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows%2064--bit-lightgrey)]()
[![Build](https://github.com/Fabianhad/OSTVisualizer-Win/actions/workflows/architecture.yml/badge.svg)](https://github.com/Fabianhad/OSTVisualizer-Win/actions/workflows/architecture.yml)

## Features

- **2D Plan View** -- Interactive view with annotations overlaid on project pages, including BidDimension placement and detached Annotation/View windows
- **PDF Plan Sheets** -- View PDF drawings at any scale
- **Multi-database** -- Open and browse Microsoft Access and Microsoft SQL Server databases together
- **Projects, Takeoff, and Summary Tabs** -- Navigate databases and bids, inspect 2D takeoffs, and review grouped condition quantities
- **Summary Review** -- Group condition quantities by Area, Type, and Page, with unused conditions hidden from placed-takeoff summaries
- **3D Visualization** -- See takeoff geometry rendered in full 3D with transparent overlays *(Commercial)*
- **Import/Export** -- Move data between OST, OSP, HTML, PDF, CSV, DXF, OBJ, and FBX formats *(Commercial)*
- **PDF Annotation Captions** -- Choose which Bluebeam-compatible measurement captions appear on exported takeoff annotations from the Options dialog *(Commercial)*
- **HTML/PDF Elevation Callouts** -- Independently include visibility-aware four-row takeoff callouts with elevations and cubic-yard quantities in HTML and PDF exports from the Options dialog *(Commercial)*
- **Condition Management** -- Create, edit, duplicate, and organize conditions across bids *(Commercial)*
- **Realtime Sync** -- Detects when On-Screen Takeoff is active and picks up changes automatically ([free companion tool](https://fabianhad.com/ost3d/download))

## Download

Download the latest installer from the [download page](https://fabianhad.com/ost3d/download):

- **`ost3dvisualizer-1.2.4.3-64.msi`** -- Windows 64-bit installer (Windows 10+)

> A [commercial license](https://fabianhad.com/ost3d/download) is required for production use. See [Licensing](#licensing).

## Licensing

This software is source-available under the [Elastic License 2.0](LICENSE).

| | Free (Viewer) | Commercial License |
|---|---|---|
| Open and browse projects | Included | Included |
| 2D plan view (read-only) | Included | Included |
| Summary tab review | Included | Included |
| 3D visualization | -- | Included |
| Edit takeoffs, conditions, bids | -- | Included |
| Import/Export (OST, OSP, HTML, PDF, CSV, DXF, OBJ, FBX) | -- | Included |
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
| Database | Microsoft Access (.mdb) and Microsoft SQL Server via pyodbc |
| Build | Nuitka, CMake |
| C++ Bindings | nanobind v2.4.0 (13 extension modules) |
| Local AI Context | Model Context Protocol via stdlib stdio helper |

## Microsoft SQL Server

Choose **Find...** in Open Files, select **Microsoft SQL Server**, and enter a
local server, named instance (`server\instance`), or host and port
(`host,port`). Windows authentication is the default. SQL Server authentication
is also supported; its password is stored in Windows Credential Manager and is
never written to `config.json` or `file_state.json`. After the server connection
is authenticated, **Database Properties (SQL Server)** lists the accessible
databases; the descriptor and credential are saved only after its final **OK**.

Microsoft ODBC Driver 18 for SQL Server is required. Connections use encryption
and trust the certificate presented by the configured SQL Server by default.
Only configure SQL Server connections to servers you control or otherwise trust.

**New Database** first offers Microsoft Access and Microsoft SQL Server. The
Access option keeps the existing local database-name workflow. The SQL Server
option uses **Database Properties (SQL Server)** to authenticate, create, and
initialize a new OST Visualizer database when the login has server
database-creation permission.
Removing a saved SQL entry removes only the local entry and its saved credential.
It never drops or deletes the SQL Server database. Unchecking an entry closes the
runtime connection while keeping it available for reconnect.

Existing unversioned SQL databases whose 64-table schema matches the Access
model can be browsed read-only. On final connection confirmation, a structurally
compatible external database can be enabled for editing after explicit
confirmation. This transaction adds only the `ostv` metadata and collaboration
tables; it does not recreate or rewrite the external application's core tables
or rows. Databases created or adopted by OST Visualizer carry an independent,
checksummed schema version and collaboration-table foundation. Schema
initialization requires additional database permissions; ordinary readers and
editors do not need server-administrator rights.

Current-schema SQL databases use one desktop session per loaded database,
server-timestamped heartbeats and bid presence, expiring resource edit locks,
and optimistic row-version checks. Writes record affected resources in the SQL
change feed in the same transaction. A background worker polls ordered deltas
and returns them through the Qt main thread so conditions, areas, takeoffs,
annotations, pages, layers, and the project tree can refresh without repeatedly
reloading the whole database. Remote changes preserve valid selection and the
same-bid 3D camera and do not enter the local undo history. Conflicting resources
become read-only until their authoritative SQL state is deliberately reloaded.
If the session or feed becomes unhealthy, SQL editing is disabled while cached
data remains viewable.

The current collaboration slice holds expiring edit locks for condition and
area editors. Other integrated writes use transaction-scoped resource locks and
row-version checks; richer in-place conflict choices and long-lived locks for
additional editing gestures remain Phase 4 work.

Collaboration covers OST Visualizer clients writing through this schema. Direct
writes by another application do not create OST Visualizer change records and
require a controlled reload or reconnect. Microsoft Access continues to use its
existing single-client workflow and starts no SQL session or polling worker.

## Local MCP Server

OST Visualizer includes an optional read-only local MCP server for MCP-compatible
clients such as Claude Desktop, Cursor, and Codex. It runs as a separate stdio
process and exposes only checked `.mdb` databases from
`~/.ost_visualizer/file_state.json`. The desktop GUI does not start the stdio
server; it only provides a live-context bridge when the app is running.

The MCP server exposes project, bid, page, layer, area, named-view, hotlink,
condition, takeoff, quantity, and structured Summary context. Summary reads use
the same grouping concepts as the desktop Summary tab: Area, Type, and Page.
The `compare_bids_by_ref_no` tool directly compares an old/source bid with a
new/target bid by condition reference number and returns bounded aggregates by
condition type with `affected_pages`; per-condition detail is opt-in.
It also includes bounded PDF text/vector summaries, page-scoped PDF text search,
page markup summaries, overlay summaries, selected-page and selected-takeoff
summaries, and lightweight scope-gap review tools. Broad result sets use
explicit limits and include status/metadata such as returned count, total count,
truncation state, and `has_more`. Local database and page source paths are
redacted to safe IDs, basenames, and path status fields.

Read-only prompts guide common workflows such as bid scope review, page QA,
markup and hotlink review, overlay/PDF context review, and quantity variance
review using the existing bounded tools.

It does not support `--database`, `--app-data-dir`, arbitrary database path
overrides, generic database access, arbitrary SQL, arbitrary file reads, shell
execution, PDF rendering, OCR, arbitrary page text dumps, unbounded PDF
text/vector extraction, CSV/export workflows, or write/mutation operations.
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
include a lightweight `ostv-mcp.exe` helper. Use `Tools > Options... > MCP Setup`
in the desktop app to copy client configuration for the packaged helper. The
setup tab only generates and copies text; it does not edit Claude Desktop,
Cursor, or Codex configuration files. After adding the configuration, restart or
reload your MCP client so it launches the helper:

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

Codex production setup uses the helper directly. Add this TOML to
`~/.codex/config.toml` or to a trusted project `.codex/config.toml`:

```toml
[mcp_servers."ost-visualizer"]
command = "C:\\Program Files\\OST Visualizer\\ostv-mcp.exe"
args = []
```

You can also register the same stdio helper with the Codex CLI:

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
.\scripts\build-visualizer.ps1 # Desktop app only -> dist_visualizer/
.\scripts\build-mcp.ps1        # MCP helper only -> dist_mcp/
.\build-msi.ps1               # Package into MSI installer
```

The combined build copies the MCP helper into the desktop distribution for MSI
packaging. The component build scripts leave their outputs independent.

For development or manual repair, per-user associations can be managed without
administrator rights:

```powershell
python tools\register_file_associations.py --exe .\venv\Scripts\python.exe --script .\Visualizer.py
python tools\register_file_associations.py --unregister
```

## Contributing

Contributions are welcome under the [Elastic License 2.0](LICENSE). By submitting a pull request, you agree that your contribution will be licensed under the same terms.

Architecture rules, conventions, and development setup are documented in [AGENTS.md](AGENTS.md). Read it before making changes. Architecture checks run automatically via pre-commit hook and CI:

```bash
python tools/check_architecture.py
```

Common validation commands:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
python tools\check_architecture.py --changed-only
git diff --check
```

Tests may require the client virtual environment with PySide6 and native-extension prerequisites installed.

## License

[Elastic License 2.0](LICENSE)
