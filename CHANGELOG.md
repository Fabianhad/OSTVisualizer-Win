# Changelog

## Unreleased

### Added

- Added first-class Microsoft SQL Server databases with encrypted Windows or SQL authentication, Windows Credential Manager secrets, saved descriptors, descriptor-stable project-tree identities, On-Screen Takeoff-compatible reader/writer role membership, rollback-safe direct canonical schema-v1 creation, mandatory snapshot-isolated commit-ordered transaction feeds, multi-user desktop sessions with presence, expiring resource locks, optimistic concurrency, race-safe bid-state/token bootstrap, local-draft protection, reconnect-safe delta polling, finite-value-validated remote takeoff graphs, self-change-safe targeted UI synchronization with context-scoped plan projection coalescing, non-blocking pending-preview takeoff placement with ordered server writes, offline local unload/removal, asynchronous deterministic shutdown, and a safe mixed-application writer gate. Microsoft Access keeps its existing workflow and does not start collaboration services.
- Added ownership-guarded Ubuntu SQL Server container provisioning, multi-address source-IP allowlisting, WireGuard admission, TLS, validation, least-privilege repair, credential rotation, backup/restore verification, recovery, and uninstall tooling; new SQL connections now validate the server certificate and hostname by default.
- Added persistent PDF annotation caption options with disabled-by-default global and per-caption controls plus Bluebeam-compatible selection, ordering, units, and formatting for all captions supported by exported polygon measurements.
- Added persistent elevation callout options for HTML and PDF exports, including independent export enablement, red default text colors, and shared condition, top elevation, bottom elevation, and cubic-yard line selection.
- Added a read-only MCP bid comparison tool that matches conditions by reference number, ignores insignificant floating-point quantity noise, and returns bounded condition-type aggregates for metadata, quantities, takeoff counts, and the pages containing affected conditions.
- Added a responsive, single-click page selector to each Cover Sheet Index cell; large projects now open without eagerly parsing every PDF, while each row still offers all available pages and labels on demand.

### Changed

- Changed source builds to require Python 3.10 or newer, matching the client syntax and native extension configuration; HTML scene DTOs no longer require Python 3.11-only typing imports.
- Changed Cover Sheet commits to perform a single post-save database refresh, reducing UI stalls after large page deletion batches.
- Changed detached plan windows to keep a successfully loaded page visible when nearby-page prefetch fails and to reveal the normal canvas when named-view navigation cannot load its target page.
- Changed embedded and detached 3D zoom controls to reject non-finite values, restore the current zoom after invalid text, and coalesce redundant docked-toolbar layout updates during resize bursts.
- Changed OST/OSP exports to reproduce original On-Screen Takeoff ordering for bid layers, bid areas, page-area settings, takeoff quantity accumulation, and generated area-condition rows; use native-compatible polygon cross-product arithmetic; preserve the original attribute order for text annotations; and omit unused access-level sections.
- Updated the main window title to show the selected database and bid alongside the OST Visualizer app name.

### Fixed

- Fixed native PDF rendering accepting invalid scales or frame coordinates that
  could overflow bitmap sizing, and explicit PDFium shutdown can now be followed
  by a clean reinitialization.
- Fixed realtime transaction monitoring leaking its opened commit-event handle
  when status-event initialization failed.
- Fixed progress dialogs intermittently destroying a worker thread before its
  queued shutdown reached the UI event loop.
- Fixed periodic license validation updating internal authorization without
  notifying the UI when a license expired, became invalid, or recovered.
- Fixed future-dated local validation timestamps extending licensed offline grace beyond its configured duration.
- Fixed malformed empty or odd-length polygon and ink data crashing plan
  annotation rendering or the native PDF writer instead of degrading safely.
- Fixed takeoff undo/redo accepting incomplete authoritative insert identities,
  which could retain stale IDs or misclassify a failed parent replay as a cycle.
- Fixed cancelling employee detail edits after navigating records retaining
  unsaved field changes in the parent Employees dialog.
- Fixed replacement or cleanup of a plan view leaving one placement signal
  connected when the other signal had already been disconnected.
- Fixed the page-area picker saving or restoring stale bid state when its
  database context is cleared while the dialog is open.
- Fixed axis-aligned curved linear takeoffs using a shorter quadratic fallback instead of their circular arc when calculating quantities.
- Fixed conflicting condition reference-number updates committing other conditions' renumbering before the target condition save; both changes now share one database transaction.
- Fixed condition-type IDs from different loaded databases overwriting each other in active-bid memory when the databases used the same numeric IDs.
- Fixed condition-property saves silently coercing invalid condition numbers or ignoring malformed spacing, and rejecting non-finite elevation, dimension, pitch, and display-size values before they can reach project storage.
- Fixed broad read-only MCP database, project, bid, hierarchy, and live-selection
  responses so they enforce result limits, report truncation metadata, cannot
  double-count repeated live selection IDs, and never expose legacy database
  entries or malformed current database entries without an explicit checked state.
- Fixed plan context menus that retained stale condition actions while paging or crashed on invalid stored annotation widths.
- Fixed overlay rectangle writes that accepted missing pages or pages with invalid calibration factors.
- Fixed HTML exports so project text cannot terminate the embedded scene-data script or inject markup into the document title.
- Fixed HTML exports reporting success when no renderable geometry was produced and no output file was written.
- Fixed PDF cache and rendering-service shutdown so one native renderer cleanup failure cannot retain the remaining per-thread renderers, dependencies are not released while a render worker is still using them, and canceled results cannot invoke a queued GUI callback.
- Fixed PDF takeoff rendering hanging on invalid converted pattern spacing, emitting zero-length diagonal artifacts where scan lines pass through polygon vertices, placing area labels or negative markers inside backout holes, and raising on malformed odd-length area coordinates.
- Fixed PDF takeoff export substituting red when a condition's valid fill color was black.
- Fixed numeric RGB and RGBA color entries being interpreted as color-and-opacity pairs.
- Fixed Summary CSV exports changing double quotes in condition names into apostrophes.
- Fixed Access database names escaping the default database directory or reaching creation with Windows-reserved path components.
- Fixed pages disappearing from the project tree when their stored page folder references a parent folder that no longer exists.
- Fixed Cover Sheet multi-file imports assigning default sheet dimensions to raster images instead of using their actual image size, and existing pages can now be moved into folders created in the same save.
- Fixed existing bid areas failing to move beneath an area created in the same save.
- Fixed multi-database project trees so a newly created folder opens rename in the correct database, grouped project selections do not duplicate operations, cross-database project selections cannot reach single-database writes, and tree rebuilds safely cancel active rename editors.
- Fixed bid-layer sidebar reloads leaving a stale new-layer editor that blocked later additions, and inline renames now reject blank names and trim surrounding whitespace.
- Fixed moving ordinary bid layers up or down reporting success without changing their stored sequence.
- Fixed workspace restoration callbacks so immediate shutdown cannot access a released window shell and delayed destruction from a replaced detached window cannot discard the replacement's persisted tracking state.
- Fixed 3D and HTML export default filenames when bid names contain Windows-reserved filename characters.
- Fixed silent toolbar check-state synchronization so it preserves signal blocks owned by an enclosing UI update.
- Fixed hidden-layer line, arrow, and dimension annotations remaining selectable through geometric fallback hit-testing.
- Fixed native 3D viewer cleanup so a renderer shutdown failure cannot retain a stale native renderer or prevent the remaining Qt-owned resources from being released.
- Fixed native 3D renderer shutdown releasing all picking and selection GPU
  resources, and malformed vertex, normal, or index buffers are rejected before
  OpenGL upload.
- Fixed page deletion failing open when MDB content verification could not finish; unavailable verification now blocks both Cover Sheet and current-page deletion instead of skipping the content warning.
- Fixed condition-sidebar refreshes so nested updates preserve their caller's Qt signal, sorting, and repaint state, and failed tree rebuilds no longer leave the sidebar permanently blocked.
- Fixed deleted takeoffs retaining stale supplemental metadata in the active project model after their visible and bid-level records were removed.
- Fixed successful plan-page renders remaining marked as pending, which could suppress later raster-quality correction; invalid overlay placement geometry now finishes loading without leaving the page busy.
- Fixed PDF export remaining unavailable for TIFF-backed pages after raster background export support was added; mixed selections now enable export whenever at least one selected page has valid dimensions.
- Fixed condition-type deletion validation failing open when usage data could not be loaded; unavailable validation now blocks deletion, direct MDB saves validate the complete deletion batch before changing any type, and schema failures are reported as failed writes.
- Fixed plan input edge cases so panning can begin at the viewport origin, horizontal-only wheel input no longer zooms out, exact zoom changes survive in-progress page renders, named-view focus synchronizes and persists the resulting zoom, keyboard moves persist once across auto-repeat and focus changes, area holes stay aligned with translated parents, canceled resize/rotation previews do not write changes, and interrupted pan, zoom-band, PDF-text, and drag interactions clean up reliably.
- Fixed named-view placement in the main plan view discarding the draft when inline naming began, and duplicate-name validation no longer opens the same warning twice.
- Fixed grouped plan-item rotation failures so later writes stop after an earlier failed stage and committed position changes remain accurately projected and undoable; mixed takeoff-and-annotation delete undo also preserves takeoff metadata captured before the database reload.
- Fixed repeated final application-close events rerunning already completed workspace and service cleanup, and one teardown failure no longer skips the remaining stages or retains released application references.
- Fixed update-dialog failures leaving later application notifications permanently suppressed.
- Fixed explicit detached annotation and named-view window restore requests being overwritten by stale saved fullscreen state.
- Fixed workspace restoration failing when saved annotation styles contain keys for tools that are no longer available.
- Fixed long-session MDB task exhaustion by explicitly releasing query cursors and reusing the committed write connection for post-save refreshes and bid exports.
- Fixed concurrent MDB creation sharing one temporary launcher, and cleanup failures no longer skip later connection teardown or hide the original schema error.
- Fixed overlay sizing for original On-Screen Takeoff databases by using each page's validated `ScaleFactor2 / ScaleFactor1` coordinate ratio for loading, movement, scale changes, and new writes, while rejecting non-finite page, canvas, and point geometry.
- Fixed native 3D page planes so every displayed page uses the final geometry elevation belonging to its own page, checking, unchecking, switching, database refreshes, and collaborative updates reliably publish one authoritative scene, detached 3D windows replay or join only a matching scene and otherwise request a fresh one, failed or stale mesh work cannot leave obsolete geometry visible, image-layer visibility changes apply immediately, ordinary page changes preserve the current 3D camera, and bid loading keeps the scene hidden until final mesh transforms are available before restoring or framing each 3D view's independent camera.
- Fixed Select Objects in Current Area so it reliably targets the focused main or detached plan surface, ignores closed surfaces, and uses real top-level windows for Qt native-window notifications and action messages.
- Fixed native 3D canvases being clipped and picking being offset on displays using non-100% scaling or after moving the app between monitors with different scaling.
- Fixed OST imports failing on safely recoverable references by validating the complete takeoff graph, preserving valid child-before-parent relationships, skipping genuinely orphaned hole/backout takeoffs and their descendants with explicit diagnostics, rejecting malformed takeoff identities, duplicate record UIDs across every section, parent cycles, and missing required page or condition references, and clearing stale selected-page or annotation takeoff attachments while continuing to reject other invalid database references.
- Fixed project-file imports so second app launches reliably forward complete OST/OSP requests to the running instance, an existing active bid remains visually selected after importing into its folder, Import remains available from the Summary tab whenever the current context permits importing, and successful menu imports warn when the database view cannot be refreshed.
- Fixed transient file-state read failures clearing the last known Open Files database list in memory.
- Fixed plan pages with both original and overlay images so hiding the image layer immediately reveals the white page canvas without an unexpected fit-to-page jump.
- Fixed overlay-only plan pages so raster overlays load without a main image and a missing overlay does not leave an unused main image pending.
- Fixed takeoff clicks after condition sidebar reloads so the clicked takeoff's condition is reselected and highlighted when the previous highlight was cleared.
- Fixed OSP exports so the embedded OST keeps the drawing paths stored in the database instead of package-internal `TempImages!.tmp` paths.
- Fixed the Select Named View dialog so refocusing a non-empty search field shows the current matching named views again.
