# AGENTS.md

This file provides guidance to Claude when working with code in this repository.

## Project Overview

OST Visualizer is a Windows desktop application for viewing and analyzing On-Screen Takeoff (OST) construction project files (.mdb databases). Built with Python/PySide6 and 13 C++17 nanobind extensions for performance-critical operations (geometry, rendering, PDF). Open-core model: community edition is a read-only 2D viewer, commercial license unlocks 3D, editing, and export.

Entry point: `Visualizer.py` -> `ost_visualizer/main.py` (single-instance enforced via `QLocalSocket`).

Client root in the full repository: `projects/ost3d/client`. App package: `projects/ost3d/client/ost_visualizer`. Server-side license code lives one level up under `projects/ost3d/routes/` and `projects/ost3d/utils/`.

## Commands

All scripts are PowerShell. Run from the client root (`projects/ost3d/client`).

```powershell
# First-time setup
.\scripts\setup.ps1          # Create venv, install Python deps (pyodbc, PySide6, Nuitka)
.\scripts\setup-cpp.ps1      # Download PDFium/QPDF, build all C++ extensions via CMake

# Development
.\scripts\run.ps1             # Activate venv and run the app
.\venv\Scripts\python.exe -m ost_visualizer.mcp_server.main # Run read-only MCP stdio server

# Release
.\scripts\build.ps1           # Nuitka standalone builds -> dist_visualizer/ and dist_mcp/
.\build-msi.ps1               # Package into MSI installer (reads version from update_check_service.py)
```

```bash
# Architecture/static checks
python tools/check_architecture.py                # Full scan
python tools/check_architecture.py --changed-only # Fast mode (staged/modified files only)
python -m unittest tests.test_plan_view_snap_helper # Focused snap-to-line checks
vulture ost_visualizer                            # Dead-code scan after new implementations
make arch-check                                   # Same as full scan
make arch-fix                                     # Print fix guidance per violation type
```

C++ extensions require Visual Studio 2022 (MSVC x64) and Qt 6.10.2 at `C:\Qt\6.10.2\msvc2022_64`. The built `.pyd` files are placed directly into the `ost_visualizer` package tree. If native snap files change, rebuild only the snap module from the configured build directory, typically `cpp_extensions/build`, with `cmake --build . --config Release --target ost_snap`. Focused unittest modules exist for recently touched behavior; run the relevant tests plus the architecture checker for changed files.

## Architecture

Clean/hexagonal architecture with four layers. Dependencies flow inward only.

```
presentation/ -> application/ -> domain/
                                   ^
                 infrastructure ----┘ (implements domain interfaces)
```

`config/di_config.py` is the composition root -- it imports all layers to wire DI. This is the only file that should cross all boundaries.

### Domain Layer (`ost_visualizer/domain/`)
Pure business logic. Dataclass entities: `Project`, `Bid`, `Page`, `Condition` (LINEAR/AREA/COUNT/ATTACHMENT), `Takeoff`, `License`. Repository interfaces defined as Protocols. Shared constants/utilities live in `domain/ost_schema.py` (MDB table-name constants shared by infrastructure readers and the `ost_exporter`) and `domain/utils/` (`position.py` for `parse_position`, `text_cleanup.py`, etc.).

**Aggregates** hold state and enforce invariants:
- `OstAggregate` - Loaded project data (projects, conditions, takeoffs, current bid)
- `ConfigAggregate` - User preferences, persisted to `~/.ost_visualizer/config.json`
- `LicenseAggregate` - License key/activation, persisted to `~/.ost_visualizer/license_cache.json`
- `FileStateAggregate` - Tracked databases, persisted to `~/.ost_visualizer/file_state.json`
- `WorkspaceStateAggregate` - Global workspace/UI shell state, persisted to `~/.ost_visualizer/workspace_state.json`

### Application Layer (`ost_visualizer/application/`)
Orchestrates domain logic. Contains:
- **Use cases** (`use_cases/`) - Single-responsibility command handlers (~50+, one per operation)
- **Orchestrators** - `VisualizationOrchestrator`, `LicenseOrchestrator`, `LifecycleOrchestrator`
- **Services** - `FileLoadingService`, `ProjectOperationsService`, `ExportService`, etc.
- **Events** (`events/app_events.py`) - Typed dataclass events published via `EventBus`
- **DTOs** (`dtos/`) - 60+ data transfer objects between layers
- **Interfaces** (`interfaces/`) - Protocols for infrastructure dependencies. Repository interfaces live in `domain/repositories/` (domain-owned ports). Renderer interfaces live in `presentation/interfaces/`
- **Builders** - `AppControllerBuilder` orchestrates DI registration via sub-builders (`ModelBuilder`, `UseCaseBuilder`, `OrchestratorBuilder`, `ServiceBuilder`)

`AppController` is the central facade: UI calls into it, it delegates to services/use cases.

### MCP Adapter (`ost_visualizer/mcp_server/`)
Standalone local Model Context Protocol server for read-only project context. It is an adapter package outside the four core layers and must not be imported by the Qt desktop startup path. The MCP entry point is `McpServer.py` / `ost_visualizer/mcp_server/main.py`; it runs over stdio as a separate process and logs only to stderr or `~/.ost_visualizer/mcp_server.log` so stdout remains reserved for MCP protocol messages. The stdio transport is implemented by the internal stdlib adapter in `ost_visualizer/mcp_server/internal_server.py`; there is no separate MCP dependency file or extra MCP setup step. Do not reintroduce an external MCP framework unless the feature scope expands to advanced protocol features such as roots, sampling, elicitation, progress/cancellation, subscriptions, logging notifications, output schemas, or complex schema validation.

MCP access is read-only and database-scoped. The adapter builds an allowlist only from `~/.ost_visualizer/file_state.json`; do not add `--database`, custom database path overrides, or other arbitrary database selection paths. It composes `MdbReader`, `MdbFileParser`, `FileProjectRepository`, and `application/services/mcp_read_service.py` directly. Broad MCP tools should expose explicit limits plus status/metadata (`returned_count`, `total_count` when cheap, and `truncated`). Current read-only estimator tools cover summaries, selected context, scope gaps, duplicate condition names, zero-quantity conditions, unplaced takeoffs, and page metadata. Do not expose arbitrary file reads, shell execution, arbitrary SQL, generic database access, PDF rendering/text extraction, 3D generation, exports, or write/edit tools through MCP. CSV export and page text through MCP are intentionally deferred until the app has polished, safe app-owned paths. Live UI context flows through `presentation/services/mcp_context_bridge.py`, an app-owned local `QLocalServer` that returns small JSON snapshots from the main Qt thread; do not read Qt widget internals directly from the MCP process.

Production builds package MCP as a separate lightweight Nuitka standalone helper directory, not inside the Qt executable. The helper executable is copied into the desktop distribution next to its required runtime DLLs. The desktop Tools menu may expose setup/copy helpers for Claude Desktop, Cursor, and Codex, but MCP-compatible clients should launch `ostv-mcp.exe` themselves over stdio. Keep the MCP helper path free of PySide6/presentation imports; the MCP-side bridge client talks to the app-owned `QLocalServer` through the compatible Windows named-pipe path.

### Infrastructure Layer (`ost_visualizer/infrastructure/`)
Implements domain interfaces:
- **MDB access** (`mdb/`) - Thread-safe `MdbConnectionManager` with separate read/write connection pools. `MdbReader` (composed of reader mixins), `MdbWriter`, `DatabaseCreator`
- **JSON persistence** (`persistence/`) - `JsonRepositoryBase` with atomic temp-file writes
- **Event bus** (`events/event_bus.py`) - Synchronous pub/sub, creates event dataclass then unpacks `vars()` as kwargs to callbacks
- **Providers** (`providers.py`, `visualization_provider.py`) - DI factories that construct presentation-layer rendering objects. These two files are the only infrastructure files allowed to import from `presentation/visualization/` (registered as exceptions in the architecture checker)
- **External** - `LicenseApiClient` (REST to fabianhad.com/ost3d/api), `HwidGenerator`
- **Monitoring** - `TransactionMonitor` watches Windows named event `Global\OSTMdbCommit` to detect when external OST is active, blocks writes accordingly

### License Client Boundary

The client calls `/validate`, `/activate`, and `/deactivate` with `license_key` and `hwid`. Activate/validate success responses must include `expiry_date` and an RSA `signature`, which `LicenseAggregate` verifies before saving `license_cache.json`. The shared parser treats malformed success bodies as server/contract failures. `LicenseOrchestrator` may use offline grace only when the server/network response is unusable and the cached license is locally valid.

Normal license denials remain separate from offline grace: not found, revoked/disabled, expired, activation limit reached, and HWID-related failures should not be converted into cached access.

The server may return `activation_count`, `max_activations`, and `active_hwids`, but the current desktop client ignores them for authorization. Service entitlements are not implemented; do not use `max_activations` as service-access gating.

### Presentation Layer (`ost_visualizer/presentation/`)
PySide6 UI. Key patterns:
- `MainWindow` receives `AppController`, creates UI via `ComponentBuilder`. It is the **presentation composition root** — the only presentation file that calls `app_controller.get_service()`. All child handlers, coordinators, and builders receive concrete services via constructor injection.
- **Coordinators** bridge events to UI: `EventCoordinator` (AppEvents -> Qt slots), `UIEventCoordinator` (button clicks -> services), `LicenseUICoordinator`
- `WorkspaceStateCoordinator` applies/restores global workspace shell state through `MainWindow`, including main-window layout, active 2D/3D view, sidebar visibility, Conditions Sidebar grouping, splitter sizes, dropdown popup sizes, and detached window state.
- **Handlers** group related UI operations: `FileOperationHandler`, `ExportHandler`, `ProjectWriteHandler`
- **Managers** (`managers/`) - Shared presentation managers for UI access/state, icons, shortcuts, context menus, and detached Annotation/View windows. `MainWindow` remains at `presentation/main_window.py` as the presentation composition root.
- **Visualization** (`visualization/`) - Qt-aware rendering pipeline: mesh generators, PDF rendering (`ost_pdf`), exporters (OSP/OST/PDF/DXF/OBJ/FBX), Three.js renderer, color service, coordinate transformer factory. Qt-aware code lives here rather than in infrastructure because it depends on PySide6 types.
- `UIStateManager` (`managers/ui_state_manager.py`) holds transient selection and placement state only (not persisted)
- `UIAccessManager` (`managers/ui_access_manager.py`) enables/disables UI elements based on license + app state. See [Permission Model](#permission-model) below

**Snap-to-line:** Current snap-to-line behavior is intentionally small and fast. Native candidate discovery lives in `cpp_extensions/src/snap/`, the Python wrapper in `presentation/components/plan_view/components/snap_index.py` exposes the native constants, and `placement_mode.py` only consumes the selected snap kind for placement behavior. Endpoint, midpoint, and perpendicular/nearest-line snapping should share the same snap tolerance path and remain deterministic. Do not add Python fallback ranking that hides native snap-index errors.

### Dependency Injection
`ServiceContainer` (`application/service_container.py`) supports three modes:
- Direct instance registration (singletons)
- Lazy singletons (created on first `get()`)
- Factories (for multi-instance creation)

Wired in `config/di_config.py` via provider classes and `AppControllerBuilder.build()`. Sub-builders (`UseCaseBuilder`, `OrchestratorBuilder`, `ServiceBuilder`) receive their dependencies as explicit parameters from `AppControllerBuilder` rather than reaching into the container themselves. The only runtime `container.get_by_interface()` call is in `LifecycleOrchestrator` to discover `IShutdownAware` participants — this is a legitimate container query with no static alternative.

## Key Patterns

**Threading**: Main Qt event loop + daemon worker threads. Two Qt signal bridges marshal worker results back to the main thread: `QtCallbackBridge` (`presentation/utils/qt_callback_bridge.py`) for license validation (300s periodic) and `OstSignaler` for transaction monitoring; `QtSceneNotifier` (`presentation/services/qt_scene_notifier.py`) for mesh generation, with a `gen_id` carried through `notify_scene_ready(..., gen_id)` so stale publishes produced by an outgoing project/bid switch are dropped on the main thread.

**Event flow**: Use case completes -> `EventBus.publish(AppEvents.X, ...)` -> `EventCoordinator` dispatches to UI slots. Events are domain events, not Qt signals. The EventBus is synchronous with no error isolation between subscribers -- a throwing subscriber breaks the chain. **Never publish events from worker threads**; the EventBus has no thread safety. Use `QtCallbackBridge` to marshal back to the main thread first.

**Projects -> Takeoff flow**: Selecting a bid on the Projects tab stages bid context only. Takeoff-specific hydration (page/sidebar restore, active page selection, placement restore, and annotation restore eligibility) happens when `UIEventCoordinator._activate_takeoff_workspace()` runs after the Takeoff tab becomes active.

**Workspace persistence**: Durable preferences stay in `config.json`. Restorable shell/UI state lives in `workspace_state.json` via `WorkspaceStateAggregate` + `WorkspaceStateCoordinator`. This includes main-window geometry/state, active 2D/3D view, sidebar visibility, Conditions Sidebar grouping, splitter sizes, dropdown popup sizes, and detached 3D / Annotation / View window state. Annotation and View window reopen are deferred until Takeoff is active and a valid page exists, and View restore remains dependent on Annotation being open first.

**Project Tree selection restore**: Treat Project Tree visual selection, current item, active bid, selected-node persistence, highlighted condition, and placement condition as separate states that must be synchronized intentionally. During internal rebuilds, snapshot the selected node before clearing the tree, do not let transient `clear()` or signal-blocked rebuilds overwrite persisted selected-node state with `None`, and compare file paths with normalized paths. Silent Project Tree restore must set the current item first, then apply visual selection; `selectionModel.select(...)` can be undone by a later `setCurrentItem(item)`. Normal refresh restore must be visual/callback-silent and must not trigger bid activation. Do not select fallback bids, roots, or first items when a saved bid is missing. `TAKEOFFS_CHANGED` fast paths may need visual selection repair without a full `DATABASE_REFRESHED`, because visual selection can drift while the internal active bid remains correct.

**Startup restored selection**: Visual restore and business activation are separate. Before consuming a restored bid selection on startup, transition the navigation state to a valid file-loaded state such as `FILE_LOADED_NO_BID`; do not add `NO_FILE -> BID_ACTIVE_*` transitions just to hide warnings. Startup activation should be explicit and ordered after file/navigation state is ready, while normal refresh restore should remain callback-silent.

**Hidden-layer conditions**: Conditions linked to hidden layers should look disabled but remain Qt-enabled/selectable enough to avoid Qt edit lifecycle warnings such as `edit: editing failed`. Use soft-disabled visuals (gray text/icons) plus explicit edit/activation guards; do not clear `Qt.ItemIsEnabled` merely to gray rows. Hidden-layer condition clicks must not enter Takeoff placement, active placement must force-exit to Select when its layer becomes hidden, and final placement guards must remain in coordinator/placement/insert paths so stale UI state cannot create invisible takeoffs. Re-enabling a layer should not auto-enter Takeoff mode unless a future feature proves a safe event/hydration path.

**Layer re-enable activation**: Manual condition clicks work because `itemClicked` emits `condition_selected` even for an already-selected item. Layer refresh restores selection with blocked signals, so no activation event fires. Do not random-patch cursor/tool state, manually check/blue toolbar actions, or auto-activate a condition merely because it became placeable. Toolbar checked/blue state must come from the normal flow: `condition_selected` -> `_on_condition_selected` -> `PlacementCoordinator.enter` -> `plan_view.activate_place_for_condition` -> `cursor_mode_change_requested("place")`. If auto-restore is revisited, first instrument and prove token creation/invalidation, plan-view condition cache freshness, `_on_condition_selected` execution, `"place"` cursor-mode emission, and that no later Select reset cancels it.

**Plan cursor/input handling**: Cursor state should be resolved through the existing cursor resolver from current interaction state. Record press-time viewport position before interaction handling and release-time viewport position before cleanup/recompute. When direct takeoff drag becomes possible, update the cursor immediately from the press location; after release, clear drag state first and recompute from the actual release position. Do not force cursors in release handlers, add timers, or duplicate cursor-setting logic. Preserve cursor priority for grips/handles, pan/zoom, and placement mode.

**Progress-backed bid paste**: Bid paste operations that may write many bids must use the existing `ProjectWriteHandler.paste_bids(...)` / `ProgressDialog` / `ProgressReporter` path. The worker thread performs DB reload work; UI-thread refresh publication happens after the dialog closes. Never publish EventBus refreshes from worker threads. Keep deleted-project and cross-file protections, right-click paste targeting the context-menu node, and Ctrl+V targeting the current selected node. Do not reintroduce synchronous direct `copy_bids()` / `move_bids()` paste from `MainWindow`.

**Project Tree actions and access guards**: UI action enablement and execution guards may both be needed: enablement for visible state, execution guards for stale `QAction` or programmatic triggers. Do not move UI access decisions into infrastructure writers or bypass `UIAccessManager` for database writes. `CREATE_DATABASE` is not the same as writes against an open/monitored MDB and should not be blocked by OST-active rules meant for existing files. Bid job-status edits are writes and must be guarded; the current-status action should be checked but disabled to avoid redundant writes. Rename commit-time guards are necessary because access can change after an inline editor opens. Renumber Conditions should use the current Conditions Sidebar visible/header sort order, confirm with `QMessageBox` ("Renumber all the conditions using the current sort order? This cannot be undone"), route through the DDD/application/writer path, and never write directly from Project Tree or Conditions Sidebar.

**Embedded 3D refresh**: Distinguish same-scene mesh updates from full bid/page/file transitions. Same bid/page edits such as takeoff deletion or layer toggles should avoid full renderer/canvas rebuilds and preserve camera. Full transitions may suspend/blank before exposing the new scene; empty/no-visible-geometry updates should blank intentionally. Do not call `clear_scene`, suspend, reset camera, or hide/show native renderer widgets for every mesh update unless the old frame is truly invalid. Avoid arbitrary timers and hide/show churn that can expose stale native-window frames.

**Refresh/debug cleanup discipline**: Remove impossible fallbacks instead of masking bugs. Do not guess fallback selection or paste targets, silently redirect invalid targets, or preserve automatic restore behavior over user intent. Qt signal blocking can change visual state without business callbacks, so inspect both visual and internal state when debugging. Use focused debug logs during investigation, then remove them. Prefer small helpers only when they remove real duplication.

**Lifecycle teardown** uses two mechanisms (a class should not normally implement both):
- `cleanup()` -- informal convention for components whose parent calls teardown directly. Used throughout the presentation hierarchy. `MainWindow.closeEvent()` calls coordinators, which cascade to child components.
- `IShutdownAware.shutdown()` -- formal ABC for container-registered components. `LifecycleOrchestrator` discovers all implementors via `get_by_interface()` and calls them with per-participant error isolation. Use this when the component has no single parent that owns its lifecycle.

Teardown order in `closeEvent()`: presentation `cleanup()` calls first, then `lifecycle_orchestrator.shutdown()` (which calls all `IShutdownAware` participants, then `app_controller.cleanup()`).

**Version**: Single source of truth is `CURRENT_VERSION` in `application/services/update_check_service.py`. The MSI build script reads it from there.

## Conventions

- No `__init__.py` files (namespace packages)
- Type hints throughout, no docstrings (clear naming preferred)
- PascalCase classes, snake_case functions, UPPER_CASE constants, `IName` for interfaces. Exception: Qt virtual method overrides use Qt's camelCase (`closeEvent`, `paintEvent`, etc.)
- Interfaces use `Protocol` (structural typing) by default. Use `ABC` only when `ServiceContainer.get_by_interface()` must discover implementors at runtime (`IShutdownAware`, `IStartable`, `IAnnotationViewManager`)
- Logging: `logging.getLogger(__name__)` at module level, or constructor-injected `self.logger` for DI-built classes. `LoggerFactory` only configures the root logger at startup (called once in `di_config.py`). Log file: `~/.ost_visualizer/app.log`
- JSON state stored in `~/.ost_visualizer/`; use `config.json` for durable preferences and `workspace_state.json` for restorable workspace/UI shell state
- Prefer explicit contracts over speculative fallbacks. Avoid broad `try/except`, `hasattr`/`getattr`, and duplicate UI action logic unless guarding a real Qt lifecycle edge (deleted `QObject`, deferred `removeEventFilter`, delayed restore on destroyed windows)
- Use cases never raise exceptions for control flow -- all errors are returned as values. Return type depends on operation: `bool` for mutations, `Optional[str]` for create (returns UID), `List[str]` for bulk create, result DTOs for operations needing error detail (`LicenseOperationResultDto`, `UpdateConditionResultDto`). Callers check truthiness for simple types, `.success` for DTOs
- Atomic JSON writes via temp file + `replace()` (see `JsonRepositoryBase`)

## Architectural Rules

**Layer boundaries:**
- Domain must never import from application, infrastructure, or presentation
- Application must never import from presentation or infrastructure (use interfaces/Protocols)
- Infrastructure may import `application/interfaces/`, `application/dtos/`, and `application/events/` -- never `application/services/` or `application/orchestrators/`. Exception: `providers.py` imports `PageLoadStrategyService` directly because it is a stateless strategy with no application-layer dependencies, instantiated as part of infrastructure's factory role
- Infrastructure must not import from presentation. Exceptions (tracked in `INFRA_PRESENTATION_VIZ_EXCEPTIONS`): `providers.py` and `visualization_provider.py` are DI factories that instantiate presentation-layer rendering objects; `osp_importer.py` uses the `ost_cab` C++ module which now lives in `presentation/visualization/exporters/`
- Presentation currently imports domain entities directly (immutable dataclasses used as DTOs) -- this is pragmatic but avoid expanding it; prefer application DTOs for new data flowing to the UI
- Presentation imports `UpdateCheckService.CURRENT_VERSION` directly (×2 files) to display the version string -- this is a constant-access shortcut, not a service call
- Only `config/di_config.py` (composition root) and `presentation/main_window.py` (presentation composition root) may resolve services from the DI container. All other presentation files receive their dependencies via constructor injection.

**Threading:**
- All UI updates must happen on the main Qt thread
- Worker threads must use `QtCallbackBridge` to communicate results back -- never call Qt APIs or publish EventBus events directly from a worker thread
- New threads should be daemon threads with explicit cleanup via `cleanup()` and `thread.join(timeout)`

**EventBus:**
- Subscribe in constructor or init, unsubscribe in `cleanup()` -- always track subscription references
- Currently 10 event types in `app_events.py`; keep events as domain outcomes, not UI actions
- Subscribers must not throw -- exceptions propagate and break remaining subscribers
- `OST_STATUS_CHANGED` is marshaled from the TransactionMonitor worker thread via `OstSignaler` (Qt signal) in `service_builder.py` -- this is the reference pattern for thread-safe EventBus publishing

**Persistence:**
- New JSON-persisted state must use `JsonRepositoryBase` for atomic writes
- Durable preferences belong in `config.json`; restorable workspace/UI shell state belongs in `workspace_state.json`
- `UIStateManager` remains runtime-only selection/placement state; do not mix it with persisted global workspace state
- Config directory: `~/.ost_visualizer/` (with fallback via `AppPaths`)

**C++ extensions:**
- All 13 extensions are required -- imports are bare (no try-except), missing `.pyd` = crash at import time
- No Python Protocol/.pyi stubs exist for most C++ modules (only `ILinearGeometry` has one). The nanobind bindings are the implicit API contract
- Extensions must not share state with each other
- `ost_renderer` supports multiple concurrent `Renderer` instances on the same thread -- each owns its own WGL context and `Scene::clear` / `Scene::add_mesh` / `Impl::resize` / `Impl::shutdown` are internally context-guarded via an RAII `ContextGuard`. If you add a new method that touches GL, it must wrap its body in `ContextGuard guard(hdc, hglrc);` too.

## Documentation Maintenance

After any refactor that changes layer boundaries, package structure, DI topology, C++ extension destinations, architectural rules, or cross-layer exceptions, update this file (`AGENTS.md`) in the **same commit** as the code change. The architecture sections, the C++ extensions table, and the architectural-rule exception lists must always match the code.

When a refactor also changes what users see, what contributors need to build, or the feature set, update `README.md` too. Internal reorganization that leaves the public surface unchanged does not require a README update.

After any release-facing update, version bump, user-visible fix, or stability improvement, update `CHANGELOG.md` for the next release, not the last released version. If the current `CHANGELOG.md` only contains notes for an already-launched version and the working tree is starting a new update cycle, replace that released-only content with a fresh section for the next version (for example, `## 1.2.3 - Unreleased`) and include only changes made since the previous release. Do not insert the new unreleased section above the released section while leaving old release notes in the file; that carries forward already-launched fixes into the next release. Do not carry forward fixes from already-launched versions, and do not edit a released section except to correct factual errors.

When `CHANGELOG.md` already has an `Unreleased` section, append the new entry under that existing section. When it only has a released heading such as `## 1.2.3 - 2026-05-19`, replace that heading and its entries with the next unreleased heading and only the new changes. The correct result is a single current unreleased section, not an unreleased section stacked above stale released entries.

Keep changelog entries separated by concern/type and preserve the existing version heading and style. Use `Added` for new user-visible capabilities or UI controls, `Changed` for behavior changes, refactors with user-visible impact, persistence changes, or altered enablement/state behavior, and `Fixed` for bug fixes and regressions. Do not put new toolbar buttons, new context-menu options, or new UI capabilities under `Fixed` unless they specifically restore broken behavior. Keep entries concise and user-visible, avoiding implementation details unless they help users understand the release note.

Example:

```markdown
### Added
- Added Undo and Redo toolbar actions for Takeoff edits.

### Changed
- Enabled Duplicate for selected takeoffs on the Takeoff tab.

### Fixed
- Fixed hidden takeoff sidebars reopening after restart.
```

A refactor counts as "big" if any of these apply:
- A sub-package moves between layers (e.g. `infrastructure/visualization/` -> `presentation/visualization/`)
- New exception lists are added to `tools/check_architecture.py`
- C++ extension `.pyd` destinations change
- The composition-root pattern changes (who resolves services from the container)
- New cross-cutting conventions are introduced (threading, persistence, lifecycle, etc.)

If unsure, update the docs -- drift is harder to fix later than prevent.

## Permission Model

`UIAccessManager` (`presentation/managers/ui_access_manager.py`) gates features via `_LICENSE_REQUIRED`. Write operations are blocked at the UI level (buttons disabled, edit triggers removed, selection disabled) rather than in handlers.

**Free (no license):**
- `VIEW_2D` — 2D plan view (read-only, selection disabled)
- `UNLOAD_FILE` — close databases
- Open/browse projects, navigate pages, view conditions

**Commercial (license required) — every write and 3D operation:**
- `VIEW_3D` — 3D mesh visualization
- `SELECT_TAKEOFFS` — select, move, rotate, delete takeoffs in both views
- `PLACE_TAKEOFF` — place new takeoffs
- `EXPORT`, `EXPORT_BID_FILE` — all export (OST and OSP share a single gating profile)
- `IMPORT` — all import
- `CREATE_DATABASE` — new OST database creation
- `DELETE_BID`, `DUPLICATE_BID`, `CREATE_FOLDER` — project tree modifications
- `EDIT_BID_JOB_STATUS` — bid job status changes from the Project Tree
- `EDIT_CONDITION`, `DUPLICATE_CONDITION`, `DELETE_CONDITION` — condition modifications
- `EDIT_PAGE_SETTINGS` — scale, area, layer rename
- `COVER_SHEET` — cover sheet editing
- `EDIT_MASTER_DATA` — database-global master data editing

**How gating works:** `ToolbarStateCoordinator.refresh()` calls `is_allowed(Feature.X)` and disables UI controls accordingly. The 3D viewer uses `set_pick_enabled(False)` + `_pick_enabled` checks in `keyPressEvent`/`contextMenuEvent`. The layers sidebar uses `set_interactive(False)` which sets `EditTrigger.NoEditTriggers`. New write operations must either be gated by an existing Feature or have a new Feature added to `_LICENSE_REQUIRED`.

Bid lock state is part of the same access model. A locked active bid blocks bid-internal editing features such as takeoff selection/placement, page/layer settings, condition create/edit/duplicate/delete, and application-level write-service mutation paths. `ActiveBidWriteGuard` is the application-layer policy shared by project and annotation write services; `UIAccessManager` is only the presentation availability layer. Bid duplicate/delete and job-status changes remain allowed because they operate outside the bid contents and allow a locked bid to be copied, removed, or moved to an unlocked status. Condition properties may still open for a locked bid, but the dialog must be read-only and save/apply paths must still be blocked below the UI. Refresh handlers must recompute the active bid lock state after database reloads before refreshing toolbar, menu, sidebar, and shortcut state.

## Architecture Enforcement

`tools/check_architecture.py` enforces the rules above. It runs automatically:
- **Pre-commit hook** (`.git/hooks/pre-commit`) — checks staged/modified files only (`--changed-only`), blocks commit on violation
- **CI** (`.github/workflows/architecture.yml`) — full scan on push to main and on pull requests

Rules:
- The checker must pass before every commit. Use `git commit --no-verify` only for emergencies
- Exceptions to architectural rules must be added explicitly to the checker (`PRESENTATION_APP_SERVICE_EXCEPTIONS`, `INFRA_APP_SERVICE_EXCEPTIONS`, `INFRA_PRESENTATION_VIZ_EXCEPTIONS`, `CPP_CROSS_LAYER_EXCEPTIONS`, `ALLOWED_ABCS`, `LOGGING_EXCLUDED_FILES`) with a comment explaining why
- New C++ modules must be added to `PYD_ALLOWED_DIRS` in the checker and the table below
- Run `make arch-fix` for guidance on resolving each violation type

## Vulture Dead-Code Scan

After any new implementation, run:

```bash
vulture ost_visualizer
```

Review every reported unused symbol before deleting anything. Do not blindly remove Vulture findings: first trace callers and verify whether the finding is genuinely unused or a false positive caused by dynamic runtime usage. Common false-positive causes in this codebase include Qt signals and slots, Qt virtual event handlers, methods connected by name or runtime wiring, callbacks registered indirectly, action handlers invoked through coordinators, properties accessed by Qt or serialization, plugin/service/provider registration, command or event handlers discovered dynamically, and nanobind/C++ extension attributes. If a finding is a known false positive, document why it is used instead of deleting it. Only remove code after confirming there is no runtime path.

Known Vulture false positives from the current `vulture ost_visualizer` output:

- `indices` in `ost_visualizer/application/dtos/scene_data_dto.py`
  - Why Vulture flags it: `SceneGeometryEntry` is a `TypedDict`, so no direct Python attribute read is visible.
  - Why it is used: `threejs_mesh_adapter.py` writes the `indices` key into scene JSON, and `presentation/visualization/renderers/threejs/templates/viewer.html` reads `geomData.indices`.
- `pdf_base64` in `ost_visualizer/application/dtos/scene_data_dto.py`
  - Why Vulture flags it: `SceneData` is a `TypedDict`, so the field declaration has no direct static read.
  - Why it is used: `threejs_renderer.py` writes `scene_data["pdf_base64"]`, and the Three.js viewer template reads `sceneData.pdf_base64`.
- `IsNegativeQuantity` in `ost_visualizer/domain/dtos/mesh_metadata_dto.py`
  - Why Vulture flags it: `MeshMetadata` is a `TypedDict`, so the field declaration has no direct static read.
  - Why it is used: mesh builders/exporters write this metadata key, and `presentation/visualization/core/boolean_operations.py` reads it with `meta.get("IsNegativeQuantity", False)`.
- `coord_scale_x`, `coord_scale_y`, `coord_offset_x`, `coord_offset_y`, `is_page_rotated`, and `auto_rotate_180` in `ost_visualizer/domain/dtos/page_render_info_dto.py`
  - Why Vulture flags them: `PageRenderInfo` is a `TypedDict`, so these declared keys do not look like normal variable reads.
  - Why they are used: `pdf_exporter.py` builds these keys in page render info, and `domain/services/coordinate_transformation_service.py` reads them via `page_info.get(...)`.
- `unraisablehook` in `ost_visualizer/main.py`
  - Why Vulture flags it: assigning `sys.unraisablehook` looks like an unused attribute assignment.
  - Why it is used: Python calls the installed unraisable-exception hook at runtime.
- `_single_instance_server` in `ost_visualizer/main.py`
  - Why Vulture flags it: the dynamic QApplication attribute is assigned but not read in Python.
  - Why it is used: storing the `QLocalServer` on the application object keeps the single-instance server alive for the process lifetime.
- `dragEnterEvent`, `dragMoveEvent`, and `dropEvent` in `ost_visualizer/presentation/components/conditions_sidebar.py`
  - Why Vulture flags them: Qt virtual event handlers are not called directly from Python.
  - Why they are used: `_ConditionsTree` enables drag/drop with `setAcceptDrops(True)` and `DragDrop`; Qt invokes these overrides during condition-folder drag/drop.
- `dragEnterEvent`, `dragMoveEvent`, and `dropEvent` in `ost_visualizer/presentation/components/project_tree_view.py`
  - Why Vulture flags them: Qt virtual event handlers are not called directly from Python.
  - Why they are used: `_BidTreeWidget` enables drag/drop with `setAcceptDrops(True)` and `DragDrop`; Qt invokes these overrides during project-tree bid moves.
- `dragEnterEvent`, `dragMoveEvent`, and `dropEvent` in `ost_visualizer/presentation/dialogs/cover_sheet/components.py`
  - Why Vulture flags them: Qt virtual event handlers are not called directly from Python.
  - Why they are used: `PlanTreeWidget` enables drag/drop with `setAcceptDrops(True)` and `DragDrop`; Qt invokes these overrides when cover-sheet pages are reordered.
- `paintEngine`, `paintEvent`, `contextMenuEvent`, and `wheelEvent` in `ost_visualizer/presentation/components/mesh_view.py`
  - Why Vulture flags them: Qt virtual methods are invoked by the Qt event loop, not by static Python calls.
  - Why they are used: `OpenGLViewer` relies on Qt to call these overrides for native painting, context menus, and wheel zoom.
- `_apply_pending` in `ost_visualizer/presentation/components/mesh_view.py`
  - Why Vulture flags it: the caller is a string-based Qt meta-object invocation.
  - Why it is used: `apply_mesh_data()` schedules it with `QtCore.QMetaObject.invokeMethod(self, "_apply_pending", QtCore.Qt.QueuedConnection)`.
- `indices` in `ost_visualizer/presentation/components/mesh_view.py`
  - Why Vulture flags it: `mesh.indices = idxs` writes a nanobind attribute that static analysis cannot follow.
  - Why it is used: `ost_renderer.MeshData.indices` is exposed in `cpp_extensions/src/module_renderer.cpp`, and `self._renderer.scene.add_mesh(mesh)` consumes it in the renderer.
- `features` in `ost_visualizer/presentation/components/page_combo.py`
  - Why Vulture flags it: `QStyleOptionViewItem.features` is a Qt option bitfield updated for framework style calculation.
  - Why it is used: the option is passed to Qt style APIs, which read the feature flag when computing the checkbox indicator rectangle.
- `wheelEvent`, `mouseDoubleClickEvent`, and `contextMenuEvent` in `ost_visualizer/presentation/components/plan_view/components/input_handler.py`
  - Why Vulture flags them: these are Qt virtual event overrides supplied through `InputHandlerMixin`, not direct Python calls.
  - Why they are used: `TakeoffPlanView` inherits `InputHandlerMixin`; Qt dispatches wheel, double-click, and context-menu events to these methods.
- `drawContents` in `ost_visualizer/presentation/components/splash_screen.py`
  - Why Vulture flags it: `QSplashScreen.drawContents()` is a Qt virtual method.
  - Why it is used: Qt calls this override when painting the splash screen.
- `filter_obj` in `ost_visualizer/presentation/interfaces/i_workspace_shell.py`
  - Why Vulture flags it: protocol method parameter names are declarations, not local runtime reads.
  - Why it is used: the protocol mirrors Qt's `installEventFilter(filter_obj)` signature for structural typing of workspace shell implementations.
- `createPopupMenu` in `ost_visualizer/presentation/main_window.py`
  - Why Vulture flags it: `QMainWindow.createPopupMenu()` is a Qt virtual method and is not called directly from Python.
  - Why it is used: Qt invokes this override when building the toolbar/context popup menu for workspace toolbar visibility.
- `source_pdf` and `is_blank` in `ost_visualizer/presentation/visualization/exporters/pdf_exporter.py`
  - Why Vulture flags them: these are writes to nanobind-exposed C++ properties.
  - Why they are used: `PageExportData.source_pdf` and `PageExportData.is_blank` are exposed in `cpp_extensions/src/module_pdf_writer.cpp` and read by C++ `merge_pages_with_annotations`.
- `strokes` in `ost_visualizer/presentation/visualization/exporters/pdf_exporter.py`
  - Why Vulture flags it: this is a write to a nanobind-exposed C++ property.
  - Why it is used: `InkAnnotationData.strokes` is exposed in `cpp_extensions/src/module_pdf_writer.cpp` and read by C++ PDF ink annotation export.
- `tint_r`, `tint_g`, and `tint_b` in `ost_visualizer/presentation/visualization/pdf/page_cache.py`
  - Why Vulture flags them: dataclass fields may appear unused because no explicit attribute reads are present.
  - Why they are used: `TintedCacheKey` is a frozen dataclass used as an `OrderedDict` cache key; these fields participate in generated equality and hashing so different tint colors cache separately.
- `database`, `bid_count`, `takeoff_count`, `condition_type_name`, `point_count`, `visible_takeoff_count`, `selected_takeoff_count`, `missing_takeoff_uids`, `uom1_label`, `uom2_label`, and `uom3_label` in `ost_visualizer/application/dtos/mcp_context_dtos.py`
  - Why Vulture flags them: MCP DTO dataclass fields are serialized with `dataclasses.asdict()` rather than read as Python attributes.
  - Why they are used: MCP hierarchy, project, page, condition, takeoff, and selected-context responses include these summary and human-readable fields for clients.
- `quantity1`, `quantity2`, `quantity3`, `uom1_label`, `uom2_label`, and `uom3_label` in `ost_visualizer/application/dtos/mcp_context_dtos.py`
  - Why Vulture flags them: MCP DTO dataclass fields are serialized with `dataclasses.asdict()` rather than read as Python attributes.
  - Why they are used: MCP quantity summary responses include these values and labels for clients.
- MCP tool/resource/prompt functions in `ost_visualizer/mcp_server/server.py`, such as `get_current_context`, `databases_resource`, `review_current_estimator_context`, and `review_takeoff_scope`
  - Why Vulture flags them: `OstMcpServer` registers these functions dynamically, so there are no direct Python calls.
  - Why they are used: MCP hosts call the registered tools, resources, and prompt through the Model Context Protocol runtime.

## C++ Extensions

13 nanobind v2.4.0 modules built via single `cpp_extensions/CMakeLists.txt`. Each copies its `.pyd` to a specific location in the Python package:

| Module | Destination | Purpose |
|--------|-------------|---------|
| `ost_geometry` | `presentation/visualization/core/` | Manifold boolean mesh ops |
| `ost_renderer` | `presentation/components/` | OpenGL 3D with OIT |
| `ost_pdf` | `presentation/visualization/pdf/` | PDFium rendering |
| `ost_pdf_writer` | `presentation/visualization/exporters/` | QPDF annotation export |
| `ost_earcut` | `presentation/visualization/core/geometry/` | Polygon triangulation |
| `ost_dxf` | `presentation/visualization/exporters/` | DXF export |
| `ost_image` | `presentation/visualization/utils/` | Image color processing |
| `ost_cab` | `presentation/visualization/exporters/` | CAB compression (imported cross-layer by `osp_importer.py` — see `CPP_CROSS_LAYER_EXCEPTIONS`) |
| `ost_winevent` | `infrastructure/monitoring/` | Windows event monitoring |
| `ost_geom_utils` | `presentation/components/plan_view/components/` | Hit testing |
| `ost_snap` | `presentation/components/plan_view/components/` | Placement snap-to-line index |
| `ost_coord_transform` | `domain/services/` | Coordinate math (only C++ module in domain) |
| `ost_linear_geom` | `presentation/visualization/core/geometry/` | Linear geometry & curves |
