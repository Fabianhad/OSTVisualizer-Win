# Changelog

## Unreleased

### Added

- Added first-class Microsoft SQL Server databases with encrypted Windows or SQL authentication, Windows Credential Manager secrets, saved descriptors, descriptor-stable project-tree identities, On-Screen Takeoff-compatible reader/writer role membership, direct canonical schema-v1 creation, mandatory snapshot-isolated commit-ordered transaction feeds, multi-user desktop sessions with presence, expiring resource locks, optimistic concurrency, local-draft protection, reconnect-safe delta polling, self-change-safe targeted UI synchronization, non-blocking pending-preview takeoff placement with ordered server writes, offline local unload/removal, asynchronous deterministic shutdown, and a safe mixed-application writer gate. Microsoft Access keeps its existing workflow and does not start collaboration services.
- Added ownership-guarded Ubuntu SQL Server container provisioning, multi-address source-IP allowlisting, WireGuard admission, TLS, validation, least-privilege repair, credential rotation, backup/restore verification, recovery, and uninstall tooling; new SQL connections now validate the server certificate and hostname by default.
- Added persistent PDF annotation caption options with disabled-by-default global and per-caption controls plus Bluebeam-compatible selection, ordering, units, and formatting for all captions supported by exported polygon measurements.
- Added persistent elevation callout options for HTML and PDF exports, including independent export enablement, red default text colors, and shared condition, top elevation, bottom elevation, and cubic-yard line selection.
- Added a read-only MCP bid comparison tool that matches conditions by reference number, ignores insignificant floating-point quantity noise, and returns bounded condition-type aggregates for metadata, quantities, takeoff counts, and the pages containing affected conditions.

### Changed

- Changed Cover Sheet commits to perform a single post-save database refresh, reducing UI stalls after large page deletion batches.
- Changed OST/OSP exports to reproduce original On-Screen Takeoff ordering for bid layers, bid areas, page-area settings, takeoff quantity accumulation, and generated area-condition rows; use native-compatible polygon cross-product arithmetic; preserve the original attribute order for text annotations; and omit unused access-level sections.
- Updated the main window title to show the selected database and bid alongside the OST Visualizer app name.

### Fixed

- Fixed long-session MDB task exhaustion by explicitly releasing query cursors and reusing the committed write connection for post-save refreshes and bid exports.
- Fixed overlay sizing for original On-Screen Takeoff databases by using the native 64-unit-per-inch overlay contract for loading, movement, and new writes. Overlays written by earlier Python builds at 96 units per inch must be recreated or explicitly migrated.
- Fixed native 3D page planes so every displayed page uses the final geometry elevation belonging to its own page, checking, unchecking, switching, database refreshes, and collaborative updates reliably publish one authoritative scene, failed or stale mesh work cannot leave obsolete geometry visible, image-layer visibility changes apply immediately, ordinary page changes preserve the current 3D camera, and bid loading keeps the scene hidden until final mesh transforms are available before restoring or framing each 3D view's independent camera.
- Fixed Select Objects in Current Area so it reliably targets the focused main or detached plan surface, ignores closed surfaces, and uses real top-level windows for Qt native-window notifications and action messages.
- Fixed native 3D canvases being clipped and picking being offset on displays using non-100% scaling or after moving the app between monitors with different scaling.
- Fixed OST imports failing on safely recoverable references by validating the complete takeoff graph, preserving valid child-before-parent relationships, skipping genuinely orphaned hole/backout takeoffs and their descendants with explicit diagnostics, rejecting malformed or ambiguous duplicate UIDs, parent cycles, and missing required page or condition references, and clearing stale selected-page or annotation takeoff attachments while continuing to reject other invalid database references.
- Fixed project-file imports so an existing active bid remains visually selected after importing into its folder, and Import remains available from the Summary tab whenever the current context permits importing.
- Fixed plan pages with both original and overlay images so hiding the image layer immediately reveals the white page canvas without an unexpected fit-to-page jump.
- Fixed takeoff clicks after condition sidebar reloads so the clicked takeoff's condition is reselected and highlighted when the previous highlight was cleared.
- Fixed OSP exports so the embedded OST keeps the drawing paths stored in the database instead of package-internal `TempImages!.tmp` paths.
- Fixed the Select Named View dialog so refocusing a non-empty search field shows the current matching named views again.
