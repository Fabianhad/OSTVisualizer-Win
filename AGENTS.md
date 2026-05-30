# AGENTS.md

Guidance for coding agents working in this repository.

## Project Snapshot

OST Visualizer is a Windows desktop app for reading On-Screen Takeoff `.mdb` files. The free edition is a read-only 2D viewer; licensed builds unlock 3D, editing, import, and export.

- Repository root is the desktop client root.
- App entry point: `Visualizer.py` -> `ost_visualizer/main.py`.
- MCP helper entry point: `McpServer.py` -> `ost_visualizer/mcp_server/main.py`.
- App package: `ost_visualizer`.
- Server-side license code lives outside this client checkout.

## Common Commands

Run PowerShell scripts from the repository root.

```powershell
.\scripts\setup.ps1
.\scripts\setup-cpp.ps1
.\scripts\run.ps1
.\scripts\build.ps1
.\build-msi.ps1
```

Useful validation:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_mcp*.py" -v
.\venv\Scripts\python.exe -m unittest discover -s tests -v
python tools\check_architecture.py
python tools\check_architecture.py --changed-only
python -m unittest tests.test_plan_view_snap_helper
vulture ost_visualizer
```

C++ extensions require Visual Studio 2022, CMake, and Qt 6.10.2 at `C:\Qt\6.10.2\msvc2022_64`. If native snap code changes, rebuild `ost_snap` from the configured CMake build directory, usually `cpp_extensions/build`.

## Architecture Guardrails

The app follows a clean/hexagonal shape:

```text
presentation -> application -> domain
                         ^
infrastructure ----------|
```

- `domain/` is pure business logic. It must not import application, infrastructure, or presentation.
- `application/` orchestrates use cases, DTOs, services, events, and interfaces. It must not import infrastructure or presentation.
- `infrastructure/` implements ports and may import approved application interfaces/DTOs/events. It must not import presentation except for architecture-checker exceptions in factory/extension integration files.
- `presentation/` is PySide6 UI. Prefer application DTOs for new data flowing to UI.
- `config/di_config.py` is the composition root and may wire all layers.
- `presentation/main_window.py` is the presentation composition root. Other presentation files should receive dependencies by constructor injection.
- `ServiceContainer.get_by_interface()` is expected only for runtime discovery such as `IShutdownAware`.

Threading and events:

- UI work must stay on the main Qt thread.
- Worker threads must marshal back through existing Qt bridges before UI updates or EventBus publication.
- Do not publish EventBus events from worker threads.
- Subscribe in constructors/init paths and unsubscribe in `cleanup()`.

Persistence:

- JSON state lives under `~/.ost_visualizer/`.
- Durable preferences belong in `config.json`.
- Restorable workspace shell state belongs in `workspace_state.json`.
- New JSON persistence should use `JsonRepositoryBase` for atomic writes.

C++ extensions:

- All 13 native modules are required and imported directly.
- Do not add Python fallback paths that hide missing native extensions.
- Add new native module destinations to `tools/check_architecture.py` and the C++ table in this file.

## MCP Guardrails

MCP is a read-only local adapter outside the core layers.

Current production path:

- Internal stdlib stdio server in `ost_visualizer/mcp_server/internal_server.py`.
- Source command: `.\venv\Scripts\python.exe -m ost_visualizer.mcp_server.main`.
- Packaged command: MCP clients launch `ostv-mcp.exe`.
- Production helper route: `McpServer.py` -> `ost_visualizer.mcp_server.main`.
- GUI app owns only the live-context bridge in `presentation/services/mcp_context_bridge.py`; it does not start the stdio MCP server.
- MCP helper path must not import PySide6, presentation startup, or `config/di_config.py`.

Do not add:

- FastMCP or MCP SDK runtime dependencies.
- Separate MCP dependency files, setup scripts, or CLI-extra install flows.
- `--database`, `--app-data-dir`, arbitrary database path overrides, arbitrary file reads, generic DB access, or arbitrary SQL.
- CSV/export, write/mutation, shell execution, PDF rendering/text extraction, OCR, or page text tools.

Database scope:

- MCP databases come only from checked entries in `~/.ost_visualizer/file_state.json`.
- Registry validation should keep missing, unchecked, non-MDB, and duplicate paths out.
- Broad MCP tools should keep bounded outputs and explicit status/metadata.

Important MCP files:

- `McpServer.py`
- `ost_visualizer/mcp_server/main.py`
- `ost_visualizer/mcp_server/internal_server.py`
- `ost_visualizer/mcp_server/server.py`
- `ost_visualizer/mcp_server/registry.py`
- `ost_visualizer/mcp_server/serializers.py`
- `ost_visualizer/mcp_server/bridge_client.py`
- `ost_visualizer/application/services/mcp_read_service.py`
- `ost_visualizer/application/dtos/mcp_context_dtos.py`
- `ost_visualizer/presentation/services/mcp_context_bridge.py`
- `ost_visualizer/presentation/utils/mcp_setup_config.py`
- `ost_visualizer/presentation/dialogs/options/components.py`
- `ost_visualizer/presentation/dialogs/options/dialog.py`
- `tests/test_mcp*.py`

Expected public MCP counts should remain 31 tools, 1 resource, 4 resource templates, and 2 prompts unless a change intentionally updates the public surface.

## Permission Model

`UIAccessManager` gates feature availability. New write operations must be tied to an existing `Feature` or add a new one in the same access model.

Free/no-license basics:

- View/open/browse projects and conditions.
- Read-only 2D plan view.
- Unload files.

License-required:

- 3D viewing.
- Takeoff selection, placement, movement, rotation, and deletion.
- Imports/exports.
- Bid, condition, page, cover-sheet, and master-data edits.

Bid lock state also blocks bid-internal editing through `ActiveBidWriteGuard`; do not rely only on disabled UI controls.

## Documentation Maintenance

Update docs in the same change when behavior changes:

- Update `AGENTS.md` for architecture, DI, MCP, threading, persistence, C++ extension, or cross-layer rule changes.
- Update `README.md` for user-visible setup, packaging, or feature changes.
- Update `CHANGELOG.md` for release-facing fixes, features, stability improvements, packaging changes, and user-visible behavior.

Keep `CHANGELOG.md` focused on the current unreleased section. Do not carry old released notes into a new unreleased section.

Changelog entries are release-facing. They should describe the meaningful user-facing or maintainer-facing difference between the last released version and the next released version, not every intermediate development step.

- Use `Added` for new user-visible features or capabilities.
- Use `Changed` for user-visible behavior changes to existing features.
- Use `Fixed` only for bugs or regressions that existed in a previous release or in a build users already received.
- Use `Removed` for user-visible features, options, or workflows that were removed.
- Use `Internal` or `Developer` only if the project already has that section and the change matters after release.

If a bug is introduced and fixed entirely inside the same `Unreleased` cycle, do not add a separate `Fixed` entry. Update the original `Added` or `Changed` entry so it describes the final behavior.

Example:

```text
Bad:
- Added: Text annotation toolbar.
- Fixed: Text annotation toolbar closed when changing font size.

Better:
- Added: Text annotation toolbar with persistent font, color, and alignment controls.
```

Do not add changelog entries for test cleanup, refactors, temporary debug logging, failed attempts, fixes to same-cycle unreleased bugs, architecture cleanup, dead-code removal, or formatting unless the result is directly user-facing or important for maintainers.

Before editing `CHANGELOG.md`, ask:

- Did this affect a released version or a build users already received?
- Is this user-visible or maintainer-facing after release?
- Is this only correcting a feature already listed under `Unreleased`?
- Should an existing `Unreleased` entry be rewritten instead of adding another entry?
- Would this entry still make sense after release?

## Static Analysis Notes

Run `vulture ost_visualizer` after significant implementation work, but do not delete findings blindly. Common false positives include:

- Qt virtual methods and slots invoked by the Qt runtime.
- String-based Qt meta-object invocations.
- TypedDict fields used through dictionary serialization.
- Dataclass DTO fields serialized with `dataclasses.asdict()`, especially MCP DTOs.
- Nanobind/C++ attributes written from Python and read by native code.
- MCP tool, resource, and prompt functions registered dynamically by `OstMcpServer`.

Document a recurring false positive only when it is still useful to future cleanup.

## C++ Extension Destinations

| Module | Destination | Purpose |
| --- | --- | --- |
| `ost_geometry` | `presentation/visualization/core/` | Manifold boolean mesh ops |
| `ost_renderer` | `presentation/components/` | OpenGL 3D with OIT |
| `ost_pdf` | `presentation/visualization/pdf/` | PDFium rendering |
| `ost_pdf_writer` | `presentation/visualization/exporters/` | QPDF annotation export |
| `ost_earcut` | `presentation/visualization/core/geometry/` | Polygon triangulation |
| `ost_dxf` | `presentation/visualization/exporters/` | DXF export |
| `ost_image` | `presentation/visualization/utils/` | Image color processing |
| `ost_cab` | `presentation/visualization/exporters/` | CAB compression |
| `ost_winevent` | `infrastructure/monitoring/` | Windows event monitoring |
| `ost_geom_utils` | `presentation/components/plan_view/components/` | Hit testing |
| `ost_snap` | `presentation/components/plan_view/components/` | Placement snap-to-line index |
| `ost_coord_transform` | `domain/services/` | Coordinate math |
| `ost_linear_geom` | `presentation/visualization/core/geometry/` | Linear geometry and curves |
