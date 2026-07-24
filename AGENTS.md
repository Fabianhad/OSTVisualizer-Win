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
.\scripts\build-visualizer.ps1
.\scripts\build-mcp.ps1
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
- Native 3D rendering uses physical pixels for viewports, framebuffers, and
  picking. Qt layouts and input remain in logical coordinates and cross the
  device-pixel-ratio boundary exactly once in `RenderSurfaceMetrics`.

Persistence:

- JSON state lives under `~/.ost_visualizer/`.
- Durable preferences belong in `config.json`.
- Restorable workspace shell state belongs in `workspace_state.json`.
- New JSON persistence should use `JsonRepositoryBase` for atomic writes.
- Saved databases use stable backend-aware descriptors in `file_state.json`.
  SQL passwords belong only in Windows Credential Manager; never place them in
  JSON, logs, exception text, labels, command lines, snapshots, or `repr` output.
- MDB `BidPages.OverlayRect` uses the page's calibrated OST coordinate space:
  units per sheet inch are `ScaleFactor2 / ScaleFactor1`. Page view state
  remains a separate 96-unit coordinate space. Overlay loading, rendering,
  movement, scale changes, and saving must use the page calibration directly,
  without PDF-, creator-, or record-format detection. Invalid or non-positive
  page calibration values produce no overlay geometry and must be rejected by
  overlay write paths rather than replaced with another coordinate basis.

Database backends:

- Backend selection occurs at the descriptor/adapter registry boundary. Shared
  application and domain workflows use stable database IDs and neutral ports.
- Microsoft Access implementation remains under `infrastructure/mdb`; Microsoft
  SQL Server implementation remains under `infrastructure/sql`. Shared schema
  semantics and explicit adapter routing live under `infrastructure/database`.
- SQL connections and cursors are per-operation leases and must not cross
  threads or escape a transaction. Never retry an uncertain SQL write.
- The only SQL schema is checksummed version 1 in `SQL_SCHEMA_V1`. New databases
  are initialized directly with that complete schema under the canonical
  `sp_getapplock` schema lock. There are no SQL schema migrations, historical
  schema definitions, compatibility aliases, or runtime upgrade paths. A
  database that does not validate as canonical v1 must be recreated.
  `SchemaRegistry` remains product data and is not the SQL schema ledger.
- External unversioned and older OST Visualizer SQL databases are not adopted or
  upgraded by the desktop client.
- Presence is informational and separate from locks. SQL write authorization
  must be enforced at the mutation boundary; toolbar/menu state is only a
  projection of the shared capability service.
- Normal SQL client/editor users must be explicit members of the built-in
  `db_datareader` and `db_datawriter` database roles. Schema visibility and
  collaboration permissions use the canonical definition in
  `infrastructure/sql/client_permissions.py`; normal clients must not receive
  `db_owner`, schema-ledger mutation, database creation, or server administration.
- Schema creation, validation, adoption, repair, and client-permission setup must
  never remove an existing login from `sysadmin` or `dbcreator`, remove its
  `db_owner` membership, or transfer database ownership away from it. Privilege
  demotion is a separate explicitly authorized administrative operation and is
  permitted only while a different authenticated sysadmin connection has been
  verified against the exact server and remains open until the reduced login
  reconnects successfully; failure must restore the original roles and owner.
- `SqlCollaborationCoordinator` owns SQL sessions, heartbeat, presence, lock
  renewal, polling, checkpoints, reconnect, and shutdown. It runs only for SQL
  descriptors, uses server UTC, drains workers outside the Qt thread on
  unload/shutdown, and crosses `QtCallbackBridge` before EventBus publication or
  UI changes. Cleanup failure is explicit and must not be reported as closed.
- Long-lived SQL edit leases are requested and released through the coordinator's
  worker command queue; presentation code must not call the collaboration store
  or wait for SQL on the Qt thread. Access receives an immediate local grant.
- SQL mutations must use `DatabaseMutationRequest`: validate the active session,
  acquire sorted resource application locks, verify owned edit-lock tokens and
  expected entity versions, change core rows, advance `EntityVersions`, and add
  operation-specific `ChangeLog` records plus exactly one `ChangeTransactions`
  marker in one transaction. Change Tracking commit versions on the marker table
  are the only durable feed checkpoints; `ChangeLog.Sequence` is diagnostic row
  order only. Each poll validates the feed epoch and minimum valid version,
  captures its high-water version, enumerates markers, and hydrates their complete
  payloads in one SQL `SNAPSHOT` transaction. Checkpoints advance only after a
  successful main-thread reconciliation. Latency-sensitive SQL takeoff placement
  uses the coordinator's bounded mutation queue; only provisional presentation
  state exists before the worker commits and returns authoritative identities
  through the Qt callback bridge. Access mutation execution preserves the existing
  MDB behavior and creates no collaboration session.
- Remote application merges are targeted by entity family. Do not publish
  EventBus events from polling workers, add remote commands to local undo
  history, reset a same-bid 3D camera, or acknowledge a batch until main-thread
  reconciliation succeeds. External writers that bypass OST Visualizer are not
  represented in this change feed.
- Takeoffs inherit bid-layer membership through their condition; `Takeoff` does
  not own a layer UID. SQL and Access share the canonical takeoff hydrator, and
  remote takeoff graphs must be validated before main-thread projection.
- Unchecking or removing a SQL descriptor always detaches local state even when
  the server is unavailable. Remote session and lock cleanup is best effort for
  this path; connection-owned leases are allowed to expire after local runtime
  generations, drafts, deferred writes, tokens, and capabilities are invalidated.
- Remote plan updates use the bounded plan-update pipeline: capture an immutable
  page snapshot on the Qt thread, prepare color and render data on a worker, and
  apply one generation-guarded scene projection on the Qt thread. The SQL feed
  checkpoint remains pending until every registered plan surface completes.
- Schema v1 includes the commit-ordered feed, writer-mode gate, and mandatory
  snapshot isolation. Mixed-application editing must remain disabled unless the
  external change adapter and canonical resource-catalog checksum are validated.

State and identity:

- Treat persisted keys, protocol values, registry keys, action IDs, cursor modes, layer IDs, and annotation/tool types as contracts. Reuse the canonical owner instead of repeating raw strings.
- Keep ownership near the concept: domain for business identifiers, application for use-case/protocol DTO values, infrastructure for storage/transport details, and presentation for UI actions, cursor modes, tool metadata, and display text.
- Do not use display labels as logic keys when a stable ID, type, enum, registry entry, or value object exists.
- Prefer registry and service lookups over type-specific branches. Special-case behavior only when the domain model proves the behavior is genuinely different.
- Mirrored UI/render state is acceptable when synchronized from an owner; avoid adding competing mutation paths or extra refresh/event dispatch paths.

C++ extensions:

- All 13 native modules are required and imported directly.
- Do not add Python fallback paths that hide missing native extensions.
- Add new native module destinations to `tools/check_architecture.py` and the C++ table in this file.

## MCP Guardrails

MCP is a read-only local adapter outside the core layers.

Runtime shape:

- Internal stdlib stdio server in `ost_visualizer/mcp_server/internal_server.py`.
- Source command: `.\venv\Scripts\python.exe -m ost_visualizer.mcp_server.main`.
- Packaged clients launch `ostv-mcp.exe`; user-facing setup details belong in `README.md` and the Options dialog MCP setup tab.
- Production helper route: `McpServer.py` -> `ost_visualizer.mcp_server.main`.
- GUI app owns only the live-context bridge in `presentation/services/mcp_context_bridge.py`; it does not start the stdio MCP server.
- MCP helper path must not import PySide6, presentation startup, or `config/di_config.py`.

Do not add:

- FastMCP or MCP SDK runtime dependencies.
- Separate MCP dependency files, setup scripts, or CLI-extra install flows.
- `--database`, `--app-data-dir`, arbitrary database path overrides, arbitrary file reads, generic DB access, or arbitrary SQL.
- CSV/export, write/mutation, shell execution, PDF rendering, OCR, arbitrary page text dumps, or unbounded PDF text/vector extraction.

Database scope:

- MCP databases come only from checked entries in `~/.ost_visualizer/file_state.json`.
- Registry validation should keep missing, unchecked, non-MDB, and duplicate paths out.
- Broad MCP tools should keep bounded outputs and explicit status/metadata.

MCP ownership map:

- `ost_visualizer/mcp_server/` owns the stdio protocol surface, registry, serializers, resources, prompts, and tool registration.
- `ost_visualizer/application/dtos/mcp_context_dtos.py` owns MCP DTOs plus protocol status/source constants.
- `ost_visualizer/application/services/mcp_read_service.py` owns read-only query behavior and bounded result shaping.
- `ost_visualizer/presentation/services/mcp_context_bridge.py` owns the GUI live-context bridge only.
- `tests/test_mcp*.py` should cover public surface counts, status/source compatibility, registry filtering, and bounded outputs.

Expected public MCP counts should remain 38 tools, 1 resource, 4 resource templates, and 7 prompts unless a change intentionally updates the public surface.

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
