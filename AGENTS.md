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
- Startup replaces the Windows platform's light-only Vista widget style with
  Fusion before creating any windows; keep the Windows 11 default style intact.
  Qt owns system theme detection, palettes, runtime palette propagation, and
  native DWM frame opt-in. Do not freeze a custom application palette or add a
  second per-window dark-frame controller. Native file dialogs remain OS-owned.
  Layers visibility checkboxes stabilize only Fusion's inactive indicator Base
  brush from the current active brush in their paint options. Preserve disabled
  palettes and interaction state; do not modify global checkbox palettes or
  cache colors across theme changes.
- Icon bindings retain the source SVG and either current-palette or explicit tool
  color policy. A later assignment replaces the previous binding for that target
  and tree column. Keep targets weakly owned, refresh existing tree icons without
  emitting edit signals, and preserve annotation tool colors during palette changes.
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
- Adjust Images and Set Scale advance their captured exact Page reference after
  their own successful MDB save reloads the authoritative Page, provided the selected
  context and edit access still match. Unrelated replacements remain invalid; never resolve by UID
  afresh on submission to bypass the dialog's ownership check.
- Context menus and internal Qt drags also run nested event loops. Bind delayed
  actions to the exact model or surface revision, selection, and authoritative
  object identities; cancel active tree drags and inline editors before deleting
  their items during a model reset. Menus opened by an embedded native render
  surface use its real top-level widget as their transient owner; a child
  `QWidgetWindow` is not a valid top-level owner. Clipboard payloads remain
  detached data, and database ownership comparisons use canonical path
  normalization. Delayed insert, paste, geometry/property-save, and delete
  selection belongs to the originating Plan surface's selection revision.
  Result-owned annotation tool reactivation validates both selection and the
  Plan-local tool revision. Cursor mode, annotation type, and placement Condition
  changes advance tool ownership independently of selection. New selection
  intent, another insertion/paste, or navigation
  supersedes it; same-page projection preserves it without coupling selection to
  rendering generations. Persisted results and undo history still complete.
  PDF text context-menu Copy captures the Page owner and exact text selection;
  replacement, clearing, or reselection invalidates the captured command.
  Project Tree multi-selection does not replace the active bid:
  toolbar and shortcut duplication target that one active bid, while context-menu
  duplication captures and revalidates the exact right-clicked bid. Other
  Project Tree context mutations likewise retain their captured database and
  resource identities; active-bid-only exports and condition renumbering are not
  offered for a different right-clicked bid. Selection-wide project commands
  carry the owning database alongside project UIDs.
  Plan scene clearing invalidates every scene-owned graphics-item reference and
  completes its internal empty-state transition before emitting selection,
  cursor, or Page-clear signals. `QGraphicsScene.clear()` destroys the C++
  graphics items synchronously, so signal-driven toolbar projection must never
  observe the prior Python wrappers during that teardown.
  Inline text edits release item/document ownership before named-view persistence
  callbacks can rebuild the scene, and scene/item replacement clears rejected or
  reentrant edits before removal. Native item/document destruction also releases
  edit ownership. A destroyed signal source is dropped without disconnecting it:
  Qt owns that disconnection, and `isValid()` may still be true during delivery.
- Progress-worker exceptions carry `None` plus the explicit exception object;
  they must not substitute a Boolean for a task's structured result. Duplicate
  Bid uses `WriteReloadResult` from service through presentation completion, so
  write failure, refresh failure, and success remain distinct and only the
  presentation owner emits the user-visible error.
- Plan Undo/Redo entries use database/Bid/Page-scoped Takeoff identity and typed
  annotation identity; a raw UID or scene key is never durable history identity.
  Mixed geometry and property replay is one application mutation on both MDB and
  SQL, and mixed deletion removes explicitly selected annotations before Takeoff
  companion cascades. An accepted asynchronous forward mutation blocks older
  Undo/Redo until its terminal result, while completed entries are ordered by
  submission rather than callback delivery. Failed or rejected persistence adds
  no history, and a still-current optimistic preview is restored without
  overwriting newer selection or tool intent. Bid-scoped local history may replay
  its persisted mutation after Page navigation, but it projects restored or
  cleared selection only while the originating exact Page object still owns that
  Plan surface; another Page or a same-UID Page replacement retains its own
  selection.
  Takeoff property, placement, and paste/delete history retains Page-scoped lifetime targets.
  Committed deletion suspends exactly those live targets; only its accepted
  restore map can reactivate them with new UIDs. A later entity reusing a deleted
  UID is a different history lifetime. Separately deleted Backouts retain their
  parent's history target as a dependency, not an implicit mutation target.
  Committed Bid Area deletion invalidates
  that Bid's Main and detached Plan history before the Area UID can be reused.
  Forward completions check their original history generation before recording
  an entry; completing persistence must not repopulate invalidated history.
  Clearing history also invalidates retained Takeoff lifetime targets, so late
  replay completions cannot suspend a new lifetime that reused their UIDs.
  Queued Area saves copy their changeset at submission, so persistence, request
  identity, and committed deletion notifications describe the same draft.
  Composite Backout restoration remaps parents restored in the same batch and
  retains independently validated external parents on both MDB and SQL.
  Restore payloads explicitly identify Takeoff sources with external parents;
  a retained parent's current UID may overlap a historical source UID without
  becoming an internal batch relationship.
- Reassign Condition explicitly expands its selected Takeoffs to their descendant
  Backouts before building updates, resource dependencies, and undo/redo history.
  Use the shared domain descendant traversal also used by property preflight;
  preserve each child's original Condition for undo. Other property commands and
  Duplicate and Reassign keep their own explicit mutation targets.
- Plan property requests capture Takeoff Page/Condition/Area/parent ownership for
  selected items and their descendant graph before entering the write scope or
  collaboration queue. Validate that complete snapshot once before any property
  writes, retaining the graph-closure guard. Descendants are validation dependencies,
  not implicit property targets; deletion and geometry retain their own selection
  contracts. MDB and SQL reject externally changed ownership under their existing
  transaction boundary. Duplicate-and-reassign Condition uses the same captured
  descendant ownership, including children retained on another Condition. Queued
  Takeoff property writes retain submission-time resource versions through the
  existing concurrency validator; later hydration cannot advance that baseline.
  SQL Takeoff preflight conflicts remain optimistic conflicts scoped to that
  Bid's Takeoff collection, not database-session failures.
  Local snapshot rejection returns the normal failed mutation result. Top-level-
  owned Plan menus validate their originating Plan's native lifetime and cleanup
  state before querying action state or dispatching commands.
- Accepted native 3D scene and texture completions may update a hidden surface's
  retained scene, but only `showEvent` may resume its renderer. Hide and cleanup
  own the suspended state even while regeneration is pending; the canonical
  renderer-resume operation must enforce that invariant for both success and
  failure completions.
  Plan surface reuse and raster/composite cache lookups share the source-file
  modification-time/size signature and explicit source revision; a stable Page
  UID and image path do not establish that previously rendered pixels are current.
  Authoritative page/database refreshes advance only the affected image-source
  revisions before projecting surfaces, including detached views.
  Scale, Page-name, and overlay-placement refreshes preserve image-source revisions;
  SQL projection may make that claim only for completely classified scale/name/
  overlay-rectangle/inversion/bitonal updates. Placement still recomposes, while
  inversion and bitonal conversion reuse the base composite. Geometry,
  overlay-coordinate calibration, controls, and 3D world dimensions still refresh.
  Normal cache lookups do not hash source files, and source revision eviction never reuses a
  previously issued revision identity.
  Ordinary Layer rename impact compares copied effective Layer snapshots before
  and after authoritative projection. Preserve raster revisions and mesh scenes
  only when UIDs, visibility, ordering, and flags match and changed names neither
  enter nor leave reserved image/annotation/comments roles. Plan/sidebar projection
  still updates labels and authoritative references. Unknown changes stay conservative.
  Complete PDF viewport compositions with PDF or TIFF Overlays share PageCache
  ownership, keyed by
  clipped viewport plus source/revision, resolution, rotation, and composition
  inputs. Incomplete Overlay and missing-metadata raster fallbacks remain
  uncached; source changes reject obsolete in-flight output. Raster completion
  is cacheable only after its source crop, tint, and draw succeed.
  Classified SQL Page updates containing only show_mode, invert, and bitonal
  carry `page_texture_only` through immediate and deferred projection. Refresh
  both native page textures without replacing accepted geometry. Source,
  calibration, placement, mixed, and unknown changes retain conservative impact.
  Page-name-only refreshes carry `mesh_scene_unchanged` through local reload and
  immediate/deferred SQL projection. Preserve accepted native scenes while normal
  label/Plan projection runs; do not infer this flag from unchanged image sources,
  since calibration, visibility, or geometry can still require scene work.
  Successful local Page name/scale saves use `PAGE_METADATA_CHANGED` after
  authoritative in-memory projection, retaining Page/Bid identity and synchronizing
  hierarchy and Cover Sheet metadata. Name-only projection updates navigation
  labels/status without rebuilding Plan or mesh; scale projection updates affected
  overlays, displayed quantities, visible Summary, and selected 3D dimensions.
  Local scale projection captures exact Page objects before persistence and
  validates the entire saved set before updating any member. Detached scale
  projection must honor a rejected overlay refresh by using the existing Page
  load boundary; never leave stale accepted rendering behind updated scale controls.
  Detached metadata consumers verify the event Bid, window Bid, and active model
  Bid before reading Page UIDs; a delayed old-Bid event cannot borrow another
  Bid's same-UID Page.
  Missing or replaced targets retain the
  conservative reload fallback. SQL feed hydration and token provenance remain
  independently authoritative. Refreshing another database updates the global
  Project Tree without reconciling the active database's workspace or mesh.
  Overlay-only canvases use the shared composite cache with source revision,
  canvas dimensions, effective page dimensions, calibration, placement/rotation,
  and tint identity. Final image effects remain downstream.
  Full base composites belong to PageCache, shared by matching Plan and native
  texture consumers. Keys include source signatures/revisions, resolution,
  raster rotation, display state, overlay transform/calibration, and effective
  page dimensions. Inversion/bitonal and final flips are applied afterward.
  Matching requests may share in-flight work; cancellation remains request-local.
  Source changes reject obsolete composition completion. Cache clearing prevents
  old work from repopulating the cache without cancelling still-valid consumers.
  Main and detached camera controls project the viewer's accepted renderable
  content, including visible page-image planes. Empty content clears zoom text
  and disables camera controls; a retained scene after regeneration failure stays
  usable. Repeated availability projection must not overwrite a typed zoom draft
  or a Main 2D control while the 3D surface is inactive.
  Deferred remote Page projection must run the existing missing-target fallback
  even when an empty Bid left the detached target UID blank, so its first new
  Page restores content and controls without manual navigation.
  Detached Plan managers consume database unload events for their own database,
  clear local history, and reproject current Page availability immediately. A
  permission-only refresh must not leave the removed database visible.
  Main's detached-Plan action uses the canonical Page-opening predicate when
  closed, but remains available to close an existing window after Page loss.
  Main Plan navigation controls require a current Page. Explicit Page clearing
  disables them and clears zoom text; visual reloads of the same Page do not
  announce a false empty state. Late zoom notifications from a cleared Plan
  must not repopulate the shared field. Page readiness restores navigation.
  Remote Page projection selects the first available Page when an empty active
  Bid gains one and synchronizes navigation when the active Page changes or
  disappears. Page-dependent toolbar actions require the Main Plan's displayed
  Page to match the authoritative active Page; deferred projection disables
  them until that context is coherent again. A successful current deferred
  completion refreshes action state before completing its projection barrier;
  stale and failed completions cannot recover controls for an older Page.
  If database refresh removes the selected Bid, clear Main Plan through the
  canonical viewer coordinator before entering the no-Bid state so pending Page
  work is invalidated along with the displayed Page. The same transition clears
  Page/3D state, restores the database-root selection, and refreshes both menu
  and toolbar state; it must not silently activate an unrelated sibling Bid.
  When refresh retains the Bid but removes its active Page, resolve the complete
  Page fallback before projecting any tab: preserve valid selected Pages, then
  choose their first Page or the first authoritative Page by sequence. Clear the
  obsolete Main Plan immediately, update Page Settings/navigation/status, and
  use the same fallback resolver for ordinary remote Page projection.
  Metadata projection remains independent of raster and mesh work: remote Bid
  hierarchy changes refresh the window title and Condition/Summary metadata
  without redrawing Plan, while Page changes refresh status, active Summary,
  Project Tree counts, and unaffected detached-Plan navigation even when their
  rendering is intentionally skipped. Condition changes update the matching
  Project Tree count without rebuilding its hierarchy. Avoid repeating Summary
  or detached navigation projection when another active-family path already owns it.
  Detached 3D context-menu zoom and reset commands reuse that window's toolbar
  actions for both enablement and execution; camera state remains surface-local.
  Main's shared zoom field retains separate unsubmitted Plan and 3D drafts across
  view switches while page/Bid context and actual zoom stay unchanged. Submission,
  camera commands, navigation, and loss of accepted 3D content discard the
  corresponding draft; inactive-view notifications must not replace active text.
  Native 3D page-image planes project the Page's shared Original/Overlay/Both
  display mode, placement, rotation, and image effects. Reuse the existing
  compositor and effect functions; do not read Original directly while showing
  Overlay/Both as selected. Local display-mode/effect projection and rollback
  refresh both native textures. A source-free page supplies no image plane.
  Remote Page projection also synchronizes shared image-mode controls; rebuilding
  native scene content alone does not update the context-menu checked state.
  Failed same-scene regeneration retains accepted geometry but reprojects current
  authoritative image state. A detached window opened during regeneration must
  receive the matching accepted scene through the validated replay path before
  failure is delivered; a destroyed window's scene snapshot is not its owner.
- Native 3D rendering uses physical pixels for viewports, framebuffers, and
  picking. Qt layouts and input remain in logical coordinates and cross the
  device-pixel-ratio boundary exactly once in `RenderSurfaceMetrics`.
- Authoritative Takeoff events refresh derived sidebar quantities even when Plan
  projection is deferred or skipped for an unaffected active Page. In 3D these
  quantities cover the selected Page set, not only the active 2D Page.
  Remote Takeoff projection carries affected Page IDs into usage-indicator and
  Area-usage refresh. Deferred Plan completion must not repeat the Takeoff
  quantity calculation already performed by authoritative projection.
  Multi-Page Takeoff control projection scans Bid-wide Area usage once, then
  updates every affected Page indicator and the active Page usage together.
  Area picker reload reuses that event's usage result; do not retain it across events.
  Mixed authoritative batches assign Summary and Page-usage work through explicit
  event facts: Area projection owns Area usage, Takeoff projection owns affected
  Page indicators, and an existing Condition/Layer rebuild owns aggregates.
  Separate later batches recompute normally; do not retain deduplication state.
  Mixed SQL batches declare when the Condition family has already projected;
  its rebuild owns quantities and Summary once from the final hydrated data.
  Takeoff projection still refreshes Page/Area usage using old and new Page
  ownership, including deletion; renderer completion does not recalculate totals.
  A mixed Page/Takeoff batch assigns Plan, mesh, quantities, Summary, and Page
  badge projection to the Page-family owner after it resolves final selection;
  do not project Takeoff-derived state first against a Page that may disappear.
  Remote Page hydration also replaces the loaded Bid and cached navigation Page
  hierarchy from the authoritative Page objects. Page folder ownership travels
  with `BidPageInfo` into `Page` through the shared MDB/SQL reader and constructor;
  do not overwrite freshly read folder assignments from cached hierarchy metadata.
  Page hydration uses the hierarchy reader's schema-aware Sequence/Name/UID order
  so equal-sequence Pages retain their navigation order after remote replacement.
  Hierarchy replacement refreshes the active Bid folder structure through the domain
  factory, then rebinds the retained authoritative Pages. Cached active Bids are
  returned only while they still exist in the current database hierarchy. Detached Page badges update for
  unaffected Page takeoff changes without requesting a canvas refresh.
- Layer deletion confirmation refreshes its in-use set from current authoritative
  content on demand. Annotation/Takeoff changes on other Pages must not leave a
  stale warning or require a Layer-tree rebuild before the next confirmation.
  Nested Condition Layer editors pass the existing backend-aware usage query to
  deletion validation instead of freezing its opening result. Query failure
  leaves the dialog intact and must not authorize deletion from stale usage.
  Bid Area editors and pickers likewise query their existing usage provider at
  deletion time. Keep the separate child-Area restriction, preserve current
  selection on query failure, and avoid scanning merely to open the editor.
- Condition **Duplicate and Reassign Takeoff** composes the existing duplicate
  use case and Plan property payload inside one database mutation. The captured
  Page/Condition/Takeoff foreign keys are verified in that transaction; queued SQL
  writes retain submission-time resource versions through the existing concurrency
  validator. Condition menu revision and Main Plan ownership guards precede
  submission, while the Plan property completion owns pending markers and history.
  Completion never submits a second reassignment, and terminal Condition callbacks
  are consumed once. Undo changes Takeoff assignments; it retains the duplicated
  Condition, as normal Condition duplication has no inverse history command.
- Condition persistence publishes one backend-neutral condition-change event
  after authoritative projection. Changed fields and mutation operation determine
  whether Plan or native-mesh regeneration is required; same-bid regeneration
  keeps the matching accepted scene visible until its generation-guarded
  replacement succeeds. Database-wide refresh remains the fallback only when
  the affected resource is not known.
  Classified local Condition updates/reorders and folder-only edits read the
  Condition/folder family through the shared reader, preserving Pages, Takeoffs,
  and Bid identity. Validate the captured Bid owner and retained Takeoff Condition
  references before replacing that family. Changed ownership and structural
  creation/deletion/copy operations retain the full reload boundary. Failed
  family reads retain the previous model and report refresh failure without
  publishing success or retrying through legacy optional-table readers.
  Rejected Condition-family ownership/graph reconciliation announces its full
  authoritative fallback as an external database refresh, not the original
  narrow field edit; consumers must invalidate the replaced graph and history.
  Scoped Area and Condition-folder reads require complete query results on both
  MDB and SQL; an error is not an empty family. Area-picker projection failure
  preserves the write-versus-refresh result and cannot assign a Page from stale
  picker output. Successful local Area projection emits the shared Area event;
  `page_controls_projected` prevents repeating controls already updated by the
  originating picker while Summary, mesh and detached consumers still run.
  Closing the Area picker does not reapply an already-projected saved family over
  later scoped updates. Cancellation preserves current selection; a selected UID
  missing from the latest picker projection is rejected without assigning it.
  Picker completion retains its Area projection revision, advanced only by its
  own save. A newer projection invalidates stale selection/cancellation even if
  an Area UID was reused; reentrant updates are not adopted as the save's revision.
  Targeted detached Page Area updates require an open window and the matching
  authoritative Bid/Page context, not just a matching Page UID.
  Classified Condition updates/reorders and folder-only hierarchy projection may transfer
  active placement to reconstructed authoritative Condition objects only after
  the complete ordered placement set still matches type and visibility. Insert,
  delete, unclassified replacement, and same-UID replacement remain strict.
  Layer visibility suspension owns the complete multi-Condition object set and
  Plan tool revision; restoration cannot override newer tool intent or access
  loss. Passive sidebar reconstruction preserves the surviving focused row, and
  toolbar placement availability follows that exact active Condition.
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
- Main's horizontal Takeoff strip uses `Config.hidden_takeoff_toolbar_items` and
  the ordered descriptors in `plan_tool_registry`. Options owns drafts until
  Apply/OK; ConfigService and APP_CONFIG_UPDATED own persistence and live
  projection. Hide toolbar presentation actions through the toolbar-owned
  visibility controller, preserving the canonical shared QAction's visibility,
  enablement, checked state, shortcut, and native toolbar focus policy. Overflow
  wrappers combine their toolbar mask with source-action visibility. Preserve the
  widgets' own enabled state across QWidgetAction visibility projection, including
  live overflow widgets; an ancestor toolbar's disabled state is not that intent.
  Failed Options saves restore the previous Config snapshot without publishing
  success, so the existing draft and reset flows can retry persistence.
  Keep the navigation spacer only when both sides contain visible controls, and collapse
  an empty strip. Unknown saved IDs are retained but ignored; defaults clear the
  hidden list. This preference does not customize workspace toolbars or detached
  surfaces, and Tools > Options remains available for recovery.
- Restorable workspace shell state belongs in `workspace_state.json`.
  Detached-window capture preserves the previous geometry/state while the window
  is hidden, including initial Page loading. Capture visible geometry/state
  changes in memory immediately, including Close before layout teardown and
  manager removal, independently of the disk-save debounce. Main hides detached
  windows before shutdown flush, so hiding must retain the latest user changes.
  Annotation and View share the Page-ready/timeout show boundary and
  Qt's `restoreGeometry()` screen, normal-geometry, and window-state restoration;
  do not apply a second frame-to-client geometry clamp after Qt restores state.
  Consume the initial show request before applying native state, so late Page
  readiness cannot re-show a window hidden for shutdown or reapply old geometry.
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
- `BidLegends.Position` stores a Legends XML blob, not a semicolon coordinate
  list. Page calibration rescales only Legends/Legend dX and dY attributes,
  preserving IDs, fonts, visibility, and extension metadata. Malformed Legend
  XML rejects the scale write. Annotation rotation slots follow the domain position
  contract (Ink first, Text index four, otherwise an odd trailing value); calibration
  preserves their precision. Annotation undo/redo snapshots and insert/paste/delete
  replay use that same rotation-slot contract when adapting to current calibration.
  Coordinate serialization uses three decimal places,
  not six significant digits. Curved Takeoff offsets remain scalable lengths.
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
- Bid Areas form a same-bid acyclic forest. MDB/SQL reconstruction, area saves,
  Duplicate Bid, and OST/OSP import reject missing, cross-bid, or cyclic area
  parents before mutation; zero-valued parents normalize to the root. Legacy
  schemas without `BidAreas.ParentUID` remain
  writable only for flat area changes. Page deletion clears surviving same-bid
  `MasterPageUID` and comment-parent references whose targets are deleted.
  Deleting takeoffs directly, through Page deletion, or through Condition
  deletion clears every surviving same-bid takeoff self-reference, including
  parent, typical-group, typical-page, and typical-group-marker links.
- Annotation insertion validates the required Page, every persisted optional
  Layer, and every positive Hot Link target against the exact target bid before
  allocating identities. Annotation creation resolves its writable default from
  that Bid's owned Layer rows, not the sidebar's cross-Bid template/visibility
  list. Without an owned Annotation Layer, retain the existing optional unassigned
  Layer contract. Explicit Layer references are never remapped by persistence.
  Unassigned annotations follow the Annotation display Layer for visibility only:
  initial Bid loading, local insertion, and remote hydration use the domain visibility
  projection without assigning its UID. Existing Plan items reproject that authoritative
  visibility on Layer changes, including hide/show and selection eligibility.
  MDB ownership rejection returns a failed mutation only after transaction rollback;
  failed annotation placement must not add model or undo state.
  OST/OSP import discards same-Bid Named Views referencing absent Pages and their
  targeting Hot Links, matching original OST import. Normalize only when those
  absent-Page references are the remaining integrity issues; malformed/duplicate
  identities, foreign ownership, and unrelated broken references still reject.
  Runtime validation remains strict.
  Named View deletion is one atomic dependency batch:
  every targeting Hot Link must be included, while Page deletion owns the
  automatic Named View/Hot Link cascade. Direct, Page, Condition, and Bid-level
  takeoff deletion all remove line, arrow, and dimension companions linked
  through either takeoff endpoint. Condition deletion also owns
  `BidConditionUser` cleanup. Page-area selection requires its Area to belong to
  the Page's bid. Deleting a Project clears both current ownership and deleted-
  bid restore references; moving a bid with an original-project value validates
  both Project identities before mutation.
- MDB and SQL bid duplication remap layer foreign keys through the shared
  `LAYER_REFERENCE_TABLES` contract. Tables such as takeoffs, dimensions,
  arrows, annotation lines, ink, and legends do not own `BidLayerUID`; takeoffs
  inherit their layer through their condition, and layerless annotation tables
  project to the canonical annotation layer.
- `BID_RELATIONSHIPS` is the complete bid ownership/reference catalog used by
  duplication; `RAW_BID_RELATIONSHIPS` is its OST/OSP import/export subset.
  Duplicate Bid regenerates each copied entity GUID and copies each table once.
  Folder parent graphs must be acyclic during hierarchy/Cover Sheet
  reconstruction, Duplicate Bid, and OST/OSP import. Ordinary MDB loading keeps
  the established missing- or cross-bid-parent fallback at the root, but new
  folder and page assignments must resolve to the exact target bid before any
  mutation. Access UID allocation for authoritative owners must reserve IDs
  still named by canonical inbound references; otherwise a dangling row
  can acquire an unrelated newly created owner after reload. This applies to
  global master-data creation and import as well as bid-owned entities. SQL
  identity allocation remains database-generated and must not run the Access
  inbound-reference `MAX(UID)` scan. A requested Condition- or Page-folder
  parent requires the corresponding optional `ParentUID` column, and any Page
  folder creation requires the folder table; reject unsupported hierarchy
  writes before changing Bid data while retaining flat root-folder writes.
  Employee saves validate every non-null Pay Class reference for the complete
  batch before the first mutation.
  `BidSettings` is an optional singular row per bid; readers, writers, imports,
  exports, and duplication reject multiple rows instead of choosing or updating
  them arbitrarily. Known page-based Cover Sheet selection identity is remapped
  through the duplicated page graph; a missing known page target is cleared in
  the duplicate, and page deletion clears it without touching other selector
  types. A duplicate receives a fresh creation time.
  Cover Sheet picker results retain their typed UID across refresh and must not
  re-resolve by display name.
  When the table exists, global `Settings` is a zero-or-one compatibility
  record. All readers and bid number allocators reject duplicate rows; a present
  but empty Settings table is initialized on the first successful allocation, and
  allocation persistence failure aborts the owning mutation. A legacy database
  without `Settings.NextBidNo` remains readable, but bid creation, import, and
  duplication must reject it instead of allocating an undurable default number.
  `BidPageSettings` may contain multiple inactive rows, but only one positive
  selected row per page is canonical. Preserve inactive rows when changing or
  clearing the page filter, and use precedence `BidAreaSelected DESC, UID DESC`
  during reconstruction, import, duplication, and malformed-row normalization.
  Page, Condition, and area deletion catalogs must stay aligned with the same
  schema relationships and remove or clear all ancillary dependents before
  deleting the owner; SQL and Access share this application-level contract.
  `BidTakeoffTotals`, `BidLaborCostCodeTotals`, and
  `BidTypicalGroupTotals` are derived calculation snapshots. Duplicate
  Bid preserves valid rows for compatibility, but omits a source total row when
  any of its bid-owned references is dangling; stale totals must not block the
  authoritative Bid graph or become retargeted through destination UID reuse.

Database backends:

- Explicit MDB refresh closes both cached read and write handles for the target
  path before reparsing, so a replaced file cannot leave reads and writes bound
  to different Access file instances. A handle that fails to close remains owned
  by the connection manager and the failure stays explicit so cleanup can retry;
  partial cleanup must not drop the only reference to that handle.
  Compact/Repair reserves the MDB and closes cached handles before capturing its
  source signature: ACE may finalize bytes and timestamps during writer close.
  Preserve physical file identity across that close, retain the reservation through
  confirmation and preparation, and release it on cancellation or failure. Worker
  preparation and replacement validate the captured source and exact loaded owner;
  never recapture an external replacement as the maintenance target.
  Authoritative post-write reload is a different lifecycle transition: it keeps
  that known database incarnation and reuses the shared serialized reader/writer
  handles. Do not route routine mutation completion through explicit refresh;
  ACE can retain process-level client tasks even after closed ODBC connections.
  Access `08004`/`-1036` connection exhaustion is a failed-before-commit result,
  is never retried blindly, and presentation owns its single user-visible error.
  A successful rollback permits reuse after a statement/schema error only while
  the handle passes the connection health probe. Connection-class errors, failed
  rollback, and failed cursor cleanup mark only that physical handle unhealthy;
  a failed close remains owned and must be retried before the handle can be used
  again. Cache and path-lock identity is absolute and Windows case-normalized.

- A saved SQL descriptor's `DatabaseGuid` is the logical database identity.
  Exactly one `DatabaseMetadata` row for OST Visualizer must exist and identify
  the current SQL Server database incarnation. Schema inspection, capability
  checks, workspace identity, mutation logging, and collaboration startup use
  that same cardinality and identity predicate before cleanup, journal recovery,
  hydration, or session creation; a database recreated under the same
  server/name is a replacement and requires an explicit re-add.

- Backend selection occurs at the descriptor/adapter registry boundary. Shared
  application and domain workflows use stable database IDs and neutral ports.
- Routed writers must explicitly dispatch every backend-specific inherited
  contract. Access Plan-item preflight uses bid-scoped Access queries, while SQL
  keeps its locked JSON preflight; backend-specific SQL must never be selected
  by Python method resolution alone. Access bulk creation allocates one
  inbound-reference-safe UID range per table and batch. Bulk Page deletion owns
  one bid-scoped preflight and applies each Page, Takeoff, annotation, settings,
  Named View, and folder cleanup relation in bounded UID sets; Cover Sheet must
  reuse that batch owner rather than restarting the cascade for each Page.
  Bid-owned identity preflight and every active bulk delete/update must keep UID
  predicates in the same bounded sets, including master-data cleanup, Condition
  and folder cascades, annotation deletion, Project/Bid operations, and shared
  Page image adjustments. Complete usage and ownership validation still finishes
  before the first write. New master-data and Bid Area batches require distinct,
  nonempty correlation UIDs before allocation; a returned UID map must identify
  every submitted row unambiguously. Forward references among new Bid Areas and
  Cover Sheet Page folders retain input-order UID allocation but insert parents
  before children so Access and FK-enforcing backends reconstruct the same graph.
  Raw bid reads for Page-owned tables without `BidUID`
  resolve ownership through one bid-scoped `BidPages` subquery; do not expand the
  complete Page list into parameters or signal a missing optional column as a
  database error. Bid-wide Page-area selection hydration uses that same set-based
  ownership boundary and applies the canonical selected-row precedence in one
  query rather than once per Page.
  Duplicate Bid remaps relationships from the actual copied rows rather than
  scanning a parent-map Cartesian product, and its table-copy helpers reuse the
  transaction's schema inspector.
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
- OST/OSP master-data reconciliation may use a format-provided weak business key
  only when it resolves to exactly one target record. Condition Type names use
  the same trimmed, case-insensitive comparison as their editor, while Employee
  imports use the existing normalized employee-number or fallback name/email key.
  Ambiguous source or target keys reject the import; UI editors retain the
  selected Job Status, Employee, Pay Class, and Condition Type UID instead of
  resolving an editable display label back to the first matching row.
  Loaded bids likewise retain `JobStatusUID`; lock evaluation, status menus,
  and status grouping use that UID while the status name remains display-only.
  Remote Job Status and Employee changes refresh hierarchy-derived labels and
  active-bid access state, while Condition Type catalog changes refresh cached
  Condition labels through `CdnTypeUID`. Employee use/deletion covers the
  estimator, project-manager, and job-site-manager bid roles by UID. Despite its
  misleading column name, `BidDPCSubscribers.BidEmployeeUID` references the global
  `Employees.UID`; Employee deletion must use that direct schema relationship,
  while `BidTimeCards.BidEmployeeUID` references `BidEmployees.UID`.
  Master-data UIDs are authoritative primary identities. Reconstruction and
  mutation must reject a malformed table containing duplicate physical
  UIDs before choosing or changing any row; display ordering must never select
  between records that claim the same UID.
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
  remote takeoff graphs must be validated before main-thread projection. Bid
  duplication reconstructs every copied internal reference from the complete
  bid relationship graph, while SQL import uses its raw interchange subset;
  regenerated row identities and GUIDs must not retain source-bid identity.
  Authoritative projects, bids, bid-owned layers, Condition/page folders, pages,
  Conditions, areas/typical areas, zones, takeoffs, and each typed annotation
  table require positive, table-wide unique integer UIDs. Access reconstruction,
  single-entity mutation/cascade, OST/OSP import, and Duplicate Bid reject
  malformed or duplicate owner identities before dictionary collapse or
  ambiguous mutation. A bid move/create must resolve its requested Project, and
  loaded takeoffs must resolve their required Page, Condition, and non-root
  Takeoff parent owners and must form an acyclic parent graph. Duplicate Bid
  rejects copied bid-internal references that are missing or belong to another
  bid before allocating destination identities, so a dangling source UID cannot
  bind to an unrelated regenerated row. Null optional references remain valid.
  Legacy UID-less `BidPageSettings` rows and intentionally orphaned hierarchy
  placement retain their separate supported compatibility contracts.
  Multi-resource Access mutations validate their complete target set before the
  first write: batch targets belong to one bid, relationship assignments resolve
  inside that bid, and root Layer/Condition-folder creation resolves the owning
  Bid before sequence or identity allocation. Takeoff, annotation, Area, and
  selected-page creation likewise require that authoritative Bid even if orphan
  companion rows carry the same Bid UID. New Bid page-folder references are
  local to the new bid, form one acyclic graph, and are inserted parent-first
  regardless of drag-produced payload order. Optional Bid Job Status, Estimator,
  Project Manager, and Site Manager references remain nullable; any value copied
  or written must resolve to its exact master-data table before the first write.
  Orphaned bid-owned rows may remain readable when their Bid is missing, but direct
  edits, moves, and deletes must resolve the authoritative owning Bid before the
  first write. When an optional Job Status or Employee master table is absent,
  unrelated Cover Sheet saves preserve the stored reference; an explicit new
  selection is unsupported and must fail without mutation.
  SQL plan preflight carries the expected Bid into its locked existence check,
  and queued Takeoff creation/paste locks every persisted Page, Condition, Area,
  and pre-existing parent Takeoff dependency. Plan paste also locks an external
  same-bid Named View referenced by a Hot Link; a cross-bid link retains that
  reference only when the Named View is part of the same copied payload.
  Plan clipboard snapshots use the current typed
  takeoff label-font state as authoritative over older raw storage extras.
- Unchecking or removing a SQL descriptor always detaches local state even when
  the server is unavailable. Remote session and lock cleanup is best effort for
  this path; connection-owned leases are allowed to expire after local runtime
  generations, drafts, deferred writes, tokens, and capabilities are invalidated.
- Remote plan updates use the bounded plan-update pipeline: capture an immutable
  page snapshot on the Qt thread, prepare color and render data on a worker, and
  apply one generation-guarded scene projection on the Qt thread. The SQL feed
  checkpoint remains pending until every registered plan surface completes.
  Accepted Main Plan projection rebinds the worker's detached Page snapshot to
  the authoritative Page before applying it, preserving the exact Page ownership
  used by context actions and selection projection.
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
- An editable empty Bid layer collection still permits creating its first
  layer; only controls that operate on existing layers are disabled.
- Page-setting controls retain Bid-owned Area choices independently from their
  active Page projection. Losing the active Page clears and disables only the
  Page-owned scale/Area selection instead of displaying state from a deleted
  Page or treating the Bid itself as unloaded.
  Detached scale controls use the shared custom-scale formatter and clear their
  value when the Page disappears. Page Area projection, including rejection
  rollback, refreshes the Main settings bar as well as all affected canvases.
- Condition Summary authoritative refreshes preserve the current row and
  expanded branches only while their complete logical tree paths still exist;
  removed rows clear selection and action availability.
- Condition and Condition-folder inline rename labels remain authoritative until
  successful persistence projects the new name. Submission, a blocked prerequisite
  flush, or SQL rejection must not leave an unpersisted label on the tree.
- Nested picker cancellation discards drafts but retains confirmed catalog
  deletions in the parent. Cover Sheet catalog refresh preserves cancelled
  pickers' parent combo draft text separately from the selected master-data UID.
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
- Active multi-Condition placement captures the authoritative Condition
  instances selected on entry. A remote delete, retype, visibility change, or
  same-UID authoritative replacement of any captured Condition exits placement.
  Layer-visibility suspension retains the exact Bid and Condition owners of the
  interrupted tool as well; showing a layer must not resume interaction against
  a replacement object that merely reuses those UIDs.
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
- Linear placement angle/distance snapping runs in OST model inches before
  transforming preview endpoints to render coordinates. Release uses the same
  model-space contract. Takeoff position writes preserve floating-point precision
  through the shared MDB/SQL serializer; do not quantize snapped coordinates again
  during insertion, geometry save, or curve updates.
- Attachment movement validates its placement anchor against its owning Area's
  transformed polygon, using the same containment semantics as placement. Reject
  an invalid group translation as a whole; do not independently snap children.
  Mouse preview and release and keyboard movement share this check. Authoritative
  refresh cancels unflushed gestures before replacing their parent objects.
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
