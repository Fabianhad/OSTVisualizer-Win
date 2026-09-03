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
PySide6 6.10.2 and the downloaded PDFium/QPDF archives are exact-version inputs;
the other Python requirements intentionally remain unpinned. Native archive URLs
and SHA-256 digests must be updated together from the authoritative upstream
release when intentionally upgrading a dependency. Native dependency extraction
uses a sibling staging directory and commits the final directory only after its
installed version validates; an existing directory must pass the same exact
version check before reuse.

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
- Declaration-only `Protocol` and `@abstractmethod` methods use `...`. Production
  exception and marker classes use a concise, meaningful docstring as their sole
  body. Intentional concrete no-op hooks use `pass`; an explicit `return None`
  is reserved for contracts where absence is the result. Test doubles follow the
  same no-op-versus-absence distinction, while empty test shell classes use
  `pass`.

Threading and events:

- UI work must stay on the main Qt thread.
- Worker threads must marshal back through existing Qt bridges before UI updates or EventBus publication.
- Do not publish EventBus events from worker threads.
- Subscribe in constructors/init paths and unsubscribe in `cleanup()`.
- Tentative application shutdown pauses shutdown-owned startup/UI continuations
  and prepares deferred persistence without destroying it. An aborted close
  resumes persistence and replays each valid continuation once in causal order;
  only terminal close discards callbacks and releases persistence dependencies.
  Cleanup owners retain failed EventBus unsubscriptions so a later cleanup can
  retry them instead of reporting a stale subscription as released. An
  in-flight EventBus publication skips subscriptions removed before their turn,
  including remove-and-readd cycles. Modal cleanup must tolerate Qt destroying
  a child with its closing parent before the nested event loop returns. Dialog-
  owned asynchronous completions and unparented `QTimer.singleShot` callbacks
  must validate the underlying Qt owner before touching widgets or projecting
  returned state.
- Native file dialogs run nested event loops. Capture the complete database/bid/
  page target before opening them, then reject the continuation if that context
  changed, the authoritative hierarchy entity was replaced even with the same
  UID, or the owning window was cleaned up or destroyed while the dialog was
  open.
- Context menus and internal Qt drags also run nested event loops. Bind delayed
  actions to the exact model or surface revision, selection, and authoritative
  object identities; cancel active tree drags and inline editors before deleting
  their items during a model reset. Clipboard payloads remain detached data, and
  database ownership comparisons use canonical path normalization.
- Native 3D rendering uses physical pixels for viewports, framebuffers, and
  picking. Qt layouts and input remain in logical coordinates and cross the
  device-pixel-ratio boundary exactly once in `RenderSurfaceMetrics`.
- Condition persistence publishes one backend-neutral condition-change event
  after authoritative projection. Changed fields and mutation operation determine
  whether Plan or native-mesh regeneration is required; same-bid regeneration
  keeps the matching accepted scene visible until its generation-guarded
  replacement succeeds. Database-wide refresh remains the fallback only when
  the affected resource is not known.
- Render-quality contracts live in `application/render_quality.py`. The
  interactive PDF baseline, raster native-pixel scale, and constrained-render
  safety floor are distinct concepts; Plan View, overlay previews, prefetch,
  composites, export rasterization, caches, and 3D page textures reuse those
  values without treating the safety floor as ordinary low quality. Zoom-based
  high-resolution rendering remains a separate dynamic policy. Raster prefetch
  admission uses native source pixel dimensions, not plan point geometry.
- PDF export requests snapshot their authoritative page, takeoff, condition,
  annotation, page-area, and display-mode state on the Qt thread after the
  destination is chosen. Export workers must not read live project entities.
- Non-rasterized PDF export uses a canonical unrotated output page. The native
  writer resolves inherited MediaBox, CropBox, UserUnit, and Rotate geometry,
  places the source page as vector content, and applies user rotation and flips
  exactly once to that content, source-PDF annotation appearances and subtype
  geometry, and exported OST annotations. Do not add annotation-specific
  offsets or separate page-transform paths. Native source placement and
  annotation conversion share `common/page_transform.hpp`;
  `PageExportData` requires explicit canonical dimensions, and non-blank pages
  also require a source path and explicit pre-rotation source dimensions.

Persistence:

- JSON state lives under `~/.ost_visualizer/`.
- Durable preferences belong in `config.json`.
- Restorable workspace shell state belongs in `workspace_state.json`.
- Resizable application-dialog dimensions and maximized state belong in the semantic
  `WorkspaceState.dialog_sizes` and `WorkspaceState.dialog_maximized` maps under
  stable presentation-owned keys. Restored normal sizes are bounded to the
  available screen, and dialogs reopen in their saved maximized or windowed
  state. Cover Sheet derives its first size from the current layout; Condition
  Types, Employees, Layers, Open Files, Bid Areas, Job Statuses, and Payroll
  Classes use their configured initial sizes. Do not store these values in
  QSettings or as opaque Qt geometry. Standard Qt dialogs retain their native
  sizing behavior and are not brought into this application-dialog policy.
- Font and color creation defaults plus the live inactive-object color belong to
  `Config` in `config.json`. Workspace annotation styles retain only alignment
  and unrelated tool defaults; explicit font and color columns on existing
  annotations and takeoffs remain authoritative. Do not mirror these settings
  into QSettings, the On-Screen Takeoff registry, or another JSON store.
- User-adjustable table and tree headers use semantic view and column IDs in
  `WorkspaceState.header_layouts`; do not add Qt opaque header blobs, QSettings,
  or per-dialog layout stores. Restore only after canonical columns exist, and
  reconcile saved semantic keys across added or removed columns instead of
  applying visual indexes to changed models. Duplicate, corrupt, or wholly
  unusable orders reset only that header layout. Restoration and model/schema
  rebuilds must not write their programmatic changes back as user preferences.
  Header-owning views require the workspace-state aggregate at construction;
  production callers must not silently fall back to nonpersistent headers.
- New JSON persistence should use `JsonRepositoryBase` for atomic writes.
- License machine identity uses only the canonical HWID v1 implementation. Read
  the SMBIOS System UUID through `GetSystemFirmwareTable`, normalize it as a UUID,
  and pin its source in the machine-scoped ProgramData identity record. A machine
  with a definitively unusable firmware UUID may pin one installation UUID there;
  a transient firmware or persistence failure must fail explicitly and must not
  select or regenerate another source. The unsupported per-user `install_id.txt`
  never participates. HWID v1 is `v1:` plus the complete uppercase SHA-256 digest,
  calculated from `OST_VISUALIZER_HWID|v1|<source>|<normalized_uuid>`, and
  license caches must carry the matching explicit HWID version.
- License activation requests require one versioned `activation_identity`
  object containing the Windows SAM-compatible account name, NetBIOS computer
  name, and the computer's domain/workgroup join type and name. Collect it only
  through the canonical Windows provider, keep it separate from HWID generation
  and signature inputs, and do not send an older payload without it. These
  client-reported fields are activation audit context, not trusted authorization
  claims or stable machine identity.
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
  Replacing an overlay resets its prior rectangle, offsets, rotation, deskew,
  and resized state. Removing it clears that same complete overlay-owned state
  and makes the original image the authoritative page display mode.

Database backends:

- A saved SQL descriptor's `DatabaseGuid` is the logical database identity.
  Collaboration startup must compare it with live `DatabaseMetadata` before
  cleanup, journal recovery, hydration, or session creation; a database recreated
  under the same server/name is a replacement and requires an explicit re-add.

- Backend selection occurs at the descriptor/adapter registry boundary. Shared
  application and domain workflows use stable database IDs and neutral ports.
- Microsoft Access implementation remains under `infrastructure/mdb`; Microsoft
  SQL Server implementation remains under `infrastructure/sql`. Shared schema
  semantics and explicit adapter routing live under `infrastructure/database`.
- SQL connections and cursors are per-operation leases and must not cross
  threads or escape a transaction. Never retry an uncertain SQL write.
- The only SQL schema is checksummed version 1 in `SQL_SCHEMA_V1`. New databases
  are initialized directly with that complete schema under the canonical
  `sp_getapplock` schema lock. The client contains no previous SQL schema
  definitions, alternate checksums, compatibility aliases, or runtime upgrade
  paths. A database that does not validate exactly as canonical v1 is rejected.
  `SchemaRegistry` remains product data and is not the SQL schema ledger.
- External unversioned and older OST Visualizer SQL databases are not adopted or
  upgraded by the desktop client.
- Presence is informational and separate from locks. SQL write authorization
  must be enforced at the mutation boundary; toolbar/menu state is only a
  projection of the shared capability service. The current bid/page is
  session-local SQL presence; navigation must not overwrite shared bid settings
  or create a durable mutation transaction.
- Collaboration heartbeats update session presence and renew owned leases; they
  must not open a second connection to repeat the complete schema/permission
  probe. Reconnection establishes capability state, and every mutation repeats
  canonical write authorization inside its transaction.
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
  Each connection instance advances a session generation within the database
  runtime; session-derived callbacks and projection barriers must validate both
  runtime and session generations. Trust loss invalidates the exact draft owners,
  while database-wide interaction cancellation belongs to the collaboration-state
  transition so delayed losses cannot cancel work acquired after reconnect.
- SQL database/session bootstrap remains on the collaboration worker, while
  explicit bid/page navigation reads use `NavigationLoadService`: prepare an
  immutable result off the Qt thread, reject stale database/bid generations,
  and project only the accepted result through `QtCallbackBridge`. Do not route
  reads through the mutation queue or expose a synchronous SQL bid-load API.
- SQL selected-page and precise page-view state are per-user workspace rows keyed
  by the authenticated SQL principal SID, database GUID, bid UID, and page UID.
  They use the dedicated asynchronous SQL workspace repository, never presence,
  local JSON, the collaboration coordinator, edit locks, mutation markers, or
  `ChangeLog`. Capture database, bid, and page identities when scheduling writes,
  restore only through an accepted navigation generation, coalesce with latest
  state winning, and bound best-effort shutdown flushes. MDB retains synchronous
  database persistence. This noncritical UI state must never prevent closing or
  own or clear live UID-based page navigation. Authoritative remote page changes
  cancel matching deferred page settings and workspace writes before a deleted
  and recreated UID can receive stale state; unrelated page and layer writes are
  retained. Other deferred project settings retain strict failure handling.
- Long-lived SQL edit leases are requested and released through the coordinator's
  worker command queue; presentation code must not call the collaboration store
  or wait for SQL on the Qt thread. Access receives an immediate local grant.
  A Condition editor owns every Condition exposed by its Previous/Next navigation,
  collection editors own the records in their authoritative opening snapshot,
  and Cover Sheet, New Project, and page-setting editors own every record their
  nested dialogs or Apply-to-All/navigation controls can mutate. Each queued
  modal save explicitly transfers that lease to the mutation and reacquires the
  same ownership before the dialog becomes interactive again. A late modal lease
  result is rejected when its original database or bid context has changed.
- Delayed SQL hierarchy and Condition mutation completions may alter selection,
  placement, or inline-edit state only while their exact captured database and
  bid/project owner is still current. Pending-operation identities include that
  owner, and temporary action blocking returns control to the canonical toolbar
  projection instead of restoring a captured enabled state.
- SQL mutations must use `DatabaseMutationRequest`: validate the active session,
  acquire sorted resource application locks, verify owned edit-lock tokens and
  expected entity versions, change core rows, advance `EntityVersions`, and add
  operation-specific `ChangeLog` records plus exactly one `ChangeTransactions`
  marker in one transaction. Change Tracking commit versions on the marker table
  are the only durable feed checkpoints; `ChangeLog.Sequence` is diagnostic row
  order only. Each poll validates the feed epoch and minimum valid version,
  captures its high-water version, enumerates markers, and hydrates their complete
  payloads in one SQL `SNAPSHOT` transaction. Checkpoints advance only after a
  successful main-thread reconciliation. All presentation-triggered SQL project,
  plan, annotation, hierarchy, settings, and master-data mutations use the
  coordinator's bounded, per-database FIFO mutation queue. Modal editors submit
  asynchronously, prevent duplicate submission, and do not treat queue
  acceptance as persistence success. Each request has a
  UUID operation ID and canonical request hash; `ChangeTransactions` stores the
  operation type and recoverable authoritative result. Never retry DML after
  commit begins: query the operation marker under its operation application lock
  and reconcile the committed transaction instead. Pending presentation state is
  non-authoritative, affected resources remain non-editable until projection, and
  undo/redo history advances only after confirmed commit and successful
  main-thread projection. Geometry previews hold coordinator-owned edit leases
  through gesture completion; selecting geometry must refresh its cursor
  affordance immediately even while a SQL lease request is pending. A queued
  mutation may be cancelled only before worker execution; if deletion is requested
  after a takeoff placement starts, retain that intent and serialize an
  authoritative delete after the placement identity commits so slow connections
  cannot resurrect the item. Provisional takeoff identities are transient,
  non-selectable pending resources; local reconciliation projects the provisional
  and authoritative UIDs as one targeted replacement and preserves other queued
  previews during unrelated remote refreshes. Queued plan geometry and property
  mutations verify every requested takeoff and annotation row inside the mutation
  transaction before any bulk write, so a concurrently deleted selection member
  rejects the whole local operation. A committed projection failure
  enters one idempotent controlled-recovery request; presentation callbacks must
  wait for the recovered completion instead of showing a premature failure or
  compensating committed data. Recovered authoritative results may project while
  editing remains disabled during catch-up, and only a failed recovery may remain
  refresh-required. Access mutation execution preserves the existing MDB behavior
  and creates no collaboration session.
- Canonical SQL validation uses parameterized set-based batches for permission/context checks,
  ordered application locks, edit-lock and rowversion validation, entity versions,
  `ChangeLog`, and the durable marker. Successfully consumed edit leases are
  deleted in the same transaction; pre-commit failure and uncertain-commit paths
  retain explicit cleanup/recovery. Takeoff-only local and remote reconciliation
  uses one snapshot with bounded multi-result hydration batches that stay below
  SQL driver parameter limits while constructing the existing validated DTO graph.
  Do not reintroduce per-resource SQL loops, a post-commit release connection for
  consumed leases, or manual optimistic projection.
  A queued edit-lease release is serviced before the next mutation so an action
  submitted immediately after selection cleanup cannot conflict with its own
  local draft; server lock and rowversion checks remain authoritative.
- SQL OST/OSP imports use one typed `PROJECT_IMPORT` mutation per file through
  the same bounded FIFO. File inspection/extraction, SQL DML, authoritative
  identity-map creation, and hydration stay off the Qt thread. Multi-file
  selection has explicit ordered per-file outcomes: an earlier committed file
  remains committed if a later file fails. Access keeps its synchronous importer.
- Remote application merges are targeted by entity family. Do not publish
  EventBus events from polling workers, add remote commands to local undo
  history, reset a same-bid 3D camera, or acknowledge a batch until main-thread
  reconciliation succeeds. Annotation entity reconciliation carries the exact
  union of its previous and authoritative page ownership so Main and detached
  Plan surfaces cancel and project only affected pages; collection-level or
  unresolved annotation changes remain conservatively bid-wide, while detached
  named-view navigation still follows the authoritative bid annotation set.
  External writers that bypass OST Visualizer are not represented in this change
  feed.
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
- `UIEventCoordinator` owns the canonical cross-view takeoff selection and its
  takeoff-to-condition sidebar projection. Direct 2D/3D user selections update
  that owner; mirrored viewer updates remain non-emitting. Explicit Plan View
  selection commands reclaim that projection even when the selected takeoff IDs
  are unchanged. Plan cursor mode is authoritative for interaction state, and
  its toolbar actions must remain in the existing exclusive action group rather
  than using signal-blocked checked states that bypass group exclusivity.
- Annotation-layer visibility is authoritative in `ProjectDataService`. Plan
  snapshots must retain hidden annotations so every open plan surface can
  reveal the existing scene items when the layer is enabled; do not filter
  hidden annotations out during viewer hydration.
- Plan mutation completions may restore previews, selections, editor properties,
  or placement tools only while their captured database, bid, and page still own
  that surface. Pending or granted geometry edit leases are released when the
  surface loses edit access, and a delayed grant must revalidate both access and
  page ownership. Main and detached Plan surfaces retain mutation history for a
  committed operation only while its captured bid remains the active history
  owner; a stale completion must not project old interaction state or attach an
  old-bid command to a newly navigated context. If authoritative hierarchy
  refresh removes the detached surface's bid, clear its undo history before
  refreshing or retargeting the window. Exact remote annotation ownership on an
  unrelated page must not clear that detached page's local undo history.
- Plan View scene bands live in `presentation/scene/plan_view_z_order.py`.
  Overlay-only imagery owns the primary page-image band, while Show Both may
  project its overlay into the foreground-image band. Base, overlay, composite,
  high-resolution, and overlay-move preview imagery must all remain below paper
  Highlights, while takeoff bodies remain above them; source type alone must
  not determine stacking.
- Multi-takeoff transforms derive one model-space selection pivot from the
  complete footprints owned by `visualization/core/geometry/takeoff_geometry.py`.
  Linear thickness, the Plan View minimum rendered line thickness, curves, Area
  vertices, and Count/Attachment dimensions, display size, shape origin,
  rotation, and minimum rendered symbol size all contribute; convert those
  display minima through the page coordinate system once. Scene-item bounds and
  condition labels do not own transform geometry. Point symbols apply their
  dimensions and display scale in local shape space before one Cartesian
  rotation; do not fold rotation into an ellipse's parametric sample angle.
  Curved Linear reflections reverse the stored signed curve offset exactly once;
  rotations preserve it.
- Multi-item movement applies one grid-snapped model-space translation to the
  complete selection. Preview, commit, Access/SQL persistence, and undo/redo
  preserve every item's original offset; do not snap each item independently.

C++ extensions:

- All 13 native modules are required and imported directly.
- Do not add Python fallback paths that hide missing native extensions.
- Add new native module destinations to `tools/check_architecture.py` and the C++ table in this file.
- Native CAB reads canonicalize source files to extended absolute Unicode paths
  for `CreateFileW`. The legacy FDI API receives only a short logical cabinet
  path and name; do not pass local, UNC, or extended-length user paths through
  FDI's ANSI path-concatenation boundary.

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

Equivalent plan actions in Main and detached windows use
`UIAccessManager.get_plan_surface_access()` with an explicit surface, database,
bid, displayed-page, and annotation-layer context. Page-scoped checks must not
fall back to the Main Window's active page, and temporary interaction blockers
are tracked per surface.
Detached Annotation and View managers receive `UIAccessManager` as a
constructor-owned dependency. Their singleton lifecycle includes in-flight
window construction; leaving the Takeoff workspace or shutting down invalidates
that lifecycle generation, closing Annotation also invalidates its dependent
View lifecycle, and a constructed window may become visible only if its
generation is still current. Exact duplicate opens coalesce, while a newer
distinct target supersedes the older request. Pending Main-window Hot Link
focus belongs to the current bid workspace and is cleared at that workspace's
ownership reset.

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
