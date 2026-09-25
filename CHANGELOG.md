# Changelog

## Unreleased

### Added

- **Options > Takeoff Toolbar** configures all 24 controls in Main's horizontal
  Takeoff strip, including annotation tools, navigation and zoom selectors, and
  grouped Scale/Area settings. Apply/OK persists visibility across restarts without
  changing shared menu commands, shortcuts, tool state, or detached windows.
  Restore Default Toolbar and Reset All Settings restore the original layout;
  hiding all controls collapses the strip, with Options remaining available.
  Showing controls preserves their current enabled state, including overflow
  controls and widgets updated while hidden.
- Condition context menus now include **Duplicate and Reassign Takeoff** below
  Duplicate. The action copies the right-clicked Condition and reassigns only its
  current-Page Takeoffs in one MDB or SQL transaction, retaining normal duplication
  behavior and reassignment history. SQL completion preserves the captured typed
  selection, including matching Takeoffs, and submission rejection restores it.
  Stale menus and queued ownership changes
  cannot redirect the operation to another Page or Condition.
- Condition context menus now include **Select Objects** below Rename to select
  that Condition's Takeoffs on the active Main Plan Page using normal
  multi-selection, including after SQL remote projection. The action requires
  matching authoritative and displayed Takeoffs and selection access; stale menus
  cannot override newer Page, Bid, Condition, selection, or tool ownership.
- Open Databases now includes Database Actions: Compact/Repair for Access MDB
  files, using DAO compaction, validated replacement, and normal database refresh.
  It reserves the database before confirmation and captures its source after
  cached writers close, avoiding false first-request database-change errors while
  continuing to reject external replacements and stale targets.
  SQL Server explicitly reports that Compact/Repair is unavailable.
- Maintenance stages output before revalidating the selected database and access,
  preserves Windows file security, and restores newer external contents if the
  source changes at replacement. Progress and shutdown cannot release ownership
  before maintenance finishes; reload failure uses canonical database unload.

### Fixed

- Linear Takeoff previews use measurement increments in model space, matching the
  released endpoint across Page scales and zoom levels. Takeoff writes retain
  coordinate precision so angled snapped geometry survives reload and undo/redo.
- Attachment Takeoff dragging and arrow-key movement stay within the owning Area,
  including polygonal boundaries and group moves. Area vertex edits cannot leave
  an attachment outside its parent.
- Reassign Condition moves selected Area Takeoffs and their Backouts together in
  one mutation. Undo restores each original Condition; stale descendants still
  reject the complete operation without partial reassignment.

- Windows 10 follows system dark mode for application widgets and supported
  native title bars by using Qt's theme-aware Fusion style. Light-mode changes
  propagate to existing Main and detached windows; Windows 11 keeps its native
  default style. Layers visibility indicators retain their color when dialogs
  take focus, while disabled indicators keep their distinct appearance.

- Detached Annotation and View windows preserve their saved size and window state
  during slow Bid reopening and capture the latest geometry before closing.
  Recent moves, resizes, and window-state changes also survive application exit
  when shutdown hides the windows before the pending workspace save.
  Late Page loading cannot re-show a window hidden for shutdown or reset its size.
  Fullscreen restoration retains the underlying normal window size instead of
  replacing it with a screen-sized rectangle.
- Arrow keys nudge selected annotations immediately after placement in Main and
  detached Plan, while retaining the active annotation tool. Inline text editing
  and scrolling with no selected movable item retain their normal behavior.
- Takeoff property undo follows authoritative Takeoff/Backout identities
  across deletion, restoration, and repeated UID allocation. Separate entities
  that reuse a UID retain separate history lifetimes, and separately restored
  Backouts follow their restored parent's current UID. Committed Bid Area deletion
  clears the owning Plan histories so older assignments cannot target a different
  Area that reused the deleted UID. Placement undo/redo shares that lifetime
  tracking, including negative, curve, and text property history. Late SQL
  completions cannot recreate invalidated history, and queued Area saves retain
  their submitted draft. MDB composite restore preserves Backouts whose parent
  remains outside the restored selection, matching SQL behavior, including when
  the parent's reallocated UID overlaps a historical Backout UID. Late undo
  completions cannot invalidate newer history after a UID is reused.
- Multi-selection Takeoff property edits validate unselected Backouts without
  changing their properties. Area assignments preserve batch atomicity and reject
  external ownership changes before writing, on both MDB and SQL.
  Duplicate-and-reassign Condition follows the same descendant contract. Queued
  property edits retain their original concurrency versions, stale local captures
  return a failed operation, and MDB rejects foreign-Bid child relationships.
  SQL ownership conflicts stay scoped to the Bid's Takeoffs without blocking
  the database session.
- Plan context menus use the top-level window as their native owner, avoiding
  Qt warnings when Plan is embedded beside a native render surface.
  Retained menus cannot dispatch commands or query annotation actions after their
  originating Plan is cleaned up or its native widget is destroyed.

- OST/OSP import now matches On-Screen Takeoff by dropping stale Named Views
  whose Pages are absent and their dependent Hot Links, while retaining valid
  views and rejecting unrelated invalid references.

- Undoing deletion of an Area with Backouts now reconnects the restored Backouts
  to the Area's new identity in Plan, including repeated undo/redo cycles.

- Ink annotations in PDF exports now retain their Page-space geometry and align
  with Takeoffs across Page rotations and flips.

- Named-view inline rename no longer raises deleted Qt item/document errors after
  a Plan refresh or rename-triggered rebuild. Subsequent clicks and renames remain
  usable in Main and detached Plan views.
- Annotation creation no longer writes global or foreign template Layer IDs.
  It uses the active Bid's owned Annotation Layer when present, otherwise leaving
  the optional Layer unassigned. Unassigned annotations retain Annotation Layer
  visibility during editing, reopening, and remote refresh without storing a
  template UID. Access ownership failures are reported without
  an unhandled exception or an invalid annotation/undo entry.
- Switching between light and dark appearance now preserves annotation toolbar
  colors and refreshes existing database and folder icons in trees and dialogs.
  Icon refresh preserves action state, tree selection, and pending edits.
- Adjust Images and Set Scale now support repeated Apply operations in the same
  dialog after an Access database reload. Failed saves log their Page context, while
  unrelated Page replacements and permission changes still prevent stale edits.
- Failed Options saves now restore the prior in-memory preferences, so retrying
  Apply or Reset All Settings persists the change and updates the UI normally.
- Plan Undo/Redo now preserves typed annotation identity when raw UIDs collide,
  deletes pasted Line/Arrow/Dimension companions before Takeoff cascades, and
  replays mixed geometry and property changes as one atomic mutation on MDB and
  SQL. Pending asynchronous mutations temporarily block older history, and
  out-of-order completions retain submission order instead of exposing an older
  destructive command. MDB Takeoff property edits now record equivalent history,
  heterogeneous prior Area values restore correctly, and rejected edits restore
  only their still-current optimistic preview. Replaying Bid-scoped local history
  after Page navigation no longer clears or replaces the current Page's selection,
  including after a same-UID Page replacement. Failed SQL property submissions
  also release their pending Takeoff markers. Repeated terminal property callbacks
  cannot clear pending markers owned by a newer operation.
- Clearing a Plan view now releases scene-owned graphics-item references and
  completes its internal empty-state transition before publishing selection,
  cursor, or Page-clear signals. Synchronous toolbar refresh can no longer access
  an `ImageBackgroundItem` after `QGraphicsScene` has destroyed its C++ owner.
- Large Access writes now allocate one collision-safe UID range per table and
  batch instead of rescanning the table and every inbound reference for each
  inserted row. Bulk Page and Cover Sheet deletion now run each cleanup relation
  in bounded UID sets instead of repeating the complete cascade and schema probe
  for every Page or folder. Master-data deletion, bid-owned ownership preflight,
  Condition/folder/annotation cleanup, Project/Bid batches, and shared Page image
  adjustments now use the same bounded predicates rather than per-row work or
  Access queries beyond its parameter limit. Duplicate Bid also remaps known
  relationships while copying and resolves indirect Area-count links from the
  rows actually copied, avoiding Cartesian update attempts, and reuses one schema
  inspector for the complete operation. Bid Area batches retain valid forward
  parents and return no generated identities when the transaction fails.
- Batched master-data saves now reject duplicate or missing temporary correlation
  UIDs before mutation instead of inserting multiple rows that collapse into one
  returned UID-map entry. Bid Area and Cover Sheet Page-folder saves now insert
  forward-referenced parents before their children while retaining input-order
  identity allocation, preserving the validated hierarchy on SQL FK backends as
  well as Access.
- Page-owned raw reads for tables without `BidUID` now use one bid-scoped Page
  subquery instead of expanding every Page UID into an Access parameter list.
  Page-area selection hydration likewise resolves the complete Bid in one query,
  preserving selected-row precedence without one SELECT per Page. The shared SQL
  reader no longer mistakes the expected missing `BidUID` capability for an ODBC
  failure.
- Routed Access Plan-item preflight now uses the shared bid-scoped MDB identity
  checks instead of inheriting SQL Server `OPENJSON` and lock-hint syntax. SQL
  Server keeps its transactional locked preflight.
- Routine Access writes now reuse the shared per-database reader/writer
  connections across their authoritative post-write reload instead of performing
  a physical ODBC reconnect after every save. Explicit refresh, replacement,
  maintenance, unload, and shutdown still close the complete database
  incarnation. ACE `08004`/`-1036` client-task exhaustion now returns a
  pre-commit failure, shows one actionable Takeoff error, preserves Plan state,
  records no undo entry, and remains retryable without an unhandled exception.
  Healthy connections now also survive rolled-back statement and schema errors;
  connection-class failures, failed rollbacks, and failed cursor cleanup evict
  the exact unhealthy handle before reuse. Windows path-case aliases share the
  same serialized cache identity.
- Remote metadata refreshes now update the Main title, Page status, active
  Summary, Project Tree Page/Condition counts, and unaffected detached-Plan Page
  labels even when raster or mesh projection is intentionally skipped. Bid-only
  hierarchy refresh no longer redraws the Main Plan, and active-family owners
  prevent duplicate Summary/navigation refreshes.
- Remote Page hydration now replaces the loaded Bid's Page hierarchy and the
  Main/detached Page pickers from the same authoritative objects, so inserted,
  removed, moved, and counted Pages do not remain stale until a hierarchy reload.
  Detached Page takeoff badges also update for changes on another Page without
  redrawing the detached canvas. Mixed Page/Takeoff batches project Plan, mesh,
  quantities, and Summary once after final Page fallback; deleting the last Page
  clears derived Condition quantities immediately.
- Database refresh now clears the stale Main Plan and invalidates its pending
  Page work when the selected Bid disappears. The deterministic fallback remains
  the database root, and menu/toolbar state now updates in the same transition.
  If the Bid survives but its active Page does not, refresh now selects the first
  valid authoritative fallback immediately even from Summary, updates Page
  Settings/navigation/status, and prevents hidden Main Plan work from retaining
  the deleted Page.
- Remote Page projection now recovers the first Page immediately when an empty
  Bid gains content, clears navigation when the last Page disappears, and keeps
  toolbar actions disabled while the authoritative active Page and displayed
  Main Plan Page differ during deferred projection. Controls recover directly
  from the successful current projection completion as soon as the matching
  Page is displayed, without waiting for another focus or navigation event.
- Fixed Duplicate Bid rejecting an otherwise valid Bid because stale derived
  total rows referenced deleted Pages or other bid-owned records. Valid derived
  totals remain compatible, while malformed `BidTakeoffTotals`,
  `BidLaborCostCodeTotals`, and `BidTypicalGroupTotals` rows are omitted from the
  duplicate without weakening required Takeoff ownership. Duplicate Bid worker
  exceptions now preserve the structured `WriteReloadResult` contract instead
  of returning `False` and crashing on `new_bid_uid`; failures produce one UI
  error, leave selection intact, and permit retry for both MDB and SQL paths.
- Bid Area dialogs and pickers now query current usage at deletion time instead
  of retaining opening snapshots; failed usage queries leave the dialog unchanged.
- Nested Condition Layer editors now validate current usage at deletion time,
  avoiding stale in-use decisions and the unnecessary opening usage scan.
- Layer deletion confirmation now reads current content usage, fixing stale
  in-use warnings after annotation removal/moves and missing warnings after insert.
- Mixed Area/Layer/Condition/Takeoff batches now refresh quantities, Summary, and
  Area usage once, while updating each affected Page indicator and Layer controls.
- Multi-Page Takeoff refreshes scan Bid Area usage once instead of once per Page;
  remote Area picker refreshes reuse the same usage result for their controls.
- Mixed Condition/Takeoff projection now calculates quantities and Condition
  Summary once from final authoritative data. SQL Takeoff changes carry old and
  new Page ownership so moves/deletions update usage on every affected Page.
- Remote Takeoff changes now update usage indicators on the affected Pages,
  including non-active Pages. Deferred Plan completion no longer recalculates
  the same Takeoff quantities a second time.
- Conditions sidebar quantities now refresh from authoritative Takeoff changes
  even when Plan projection is deferred or unnecessary, including remote changes
  on another Page in the selected 3D Page set.
- Annotation history replay now preserves rotation when adapting saved positions
  to current page calibration, including geometry undo/redo, insert/paste redo,
  and delete undo. Takeoff length offsets retain their existing scaling.
- Page-scale writes preserve the canonical annotation angle slot (including leading
  Ink rotation) without rounding it. Coordinate serialization retains three decimal
  places even for large coordinates instead of truncating to six significant digits.
- Page calibration now rescales Legend XML coordinates instead of treating their
  Position blob as a numeric list, preserving Legend metadata. Text/Rectangle/Oval
  rotation values remain unchanged while their coordinates rescale.
- Ordinary Layer renames now preserve PDF source revisions and accepted native
  meshes when effective Layer identity, visibility, ordering, and flags are
  unchanged. Reserved-role renames and membership changes remain conservative
  across MDB and immediate/deferred SQL projection.
- Matching complete PDF viewport composites with PDF or TIFF Overlays now share
  bounded cache/in-flight ownership, avoiding repeated TIFF crop/tint/composition.
  Keys include the clipped viewport and existing composition inputs; incomplete
  source/metadata fallbacks stay uncached and old source results are rejected.
- Remote display-mode, inversion, and bitonal updates now refresh Main/detached
  3D textures without regenerating unchanged meshes, matching local projection.
  Immediate and deferred SQL reconciliation retain conservative handling for
  source, geometry, mixed, and unknown changes.
- Page-name-only saves and immediate/deferred SQL projection retain accepted 3D
  scenes without clearing surfaces or regenerating meshes. Other Page changes
  retain conservative scene invalidation.
- Main and detached native textures reuse matching Overlay-only canvases through
  the shared composite cache, including placement, tint, dimensions, calibration,
  and source revisions. Obsolete source completions cannot populate that cache.
- Matching Plan and native texture consumers now share bounded full-composite
  caching and in-flight work through PageCache. Source changes reject stale
  completions; cache clears prevent old work from repopulating the cache. Page
  dimensions now participate in composite keys.
- Overlay-placement saves now recompose without rerasterizing unchanged PDFs.
  Classified SQL inversion and bitonal updates reuse source rasters and base
  composites while updating effect pixels in Plan and native page textures.
- Page rename refreshes now reuse unchanged PDF rasters in Main and detached Plan
  and native page textures. Local saves and classified SQL name/scale updates
  preserve source revisions while page labels still refresh.
- Scale-only saves and classified SQL scale projections now preserve PDF source
  revisions and cached rasters while updating Plan controls and calibrated 3D
  dimensions. Unclassified and image-changing refreshes retain invalidation.
- Fixed stale PDF text Copy menus in Main and detached Plan copying a newer
  selection after the Page or selected text changed while the menu was open.
- Fixed the detached-Plan menu action remaining enabled with no valid Page even
  though opening was rejected. It recovers with a Page and still allows closing
  an existing detached window after its Page disappears.
- Fixed detached Plan staying blank when an empty Bid receives its first Page
  through deferred remote projection. The existing missing-Page fallback now
  restores the Page, scale, and navigation without reopening the window.
- Fixed open detached Plans retaining the removed database's Page and selection
  after unload. Matching windows now clear content, navigation, scale, Area, and
  local history immediately; unrelated database unloads leave them unchanged.
- Fixed Main Plan retaining enabled navigation controls and stale zoom text after
  its Page disappears. Controls now recover with a valid Page, and late zoom
  notifications cannot refill the empty field.
- Fixed remote Page display-mode changes leaving Main and detached 3D context
  menus checked against the previous mode after their textures refreshed.
- Fixed Main and detached 3D page-image planes always rendering Original despite
  Overlay/Both controls showing another mode, and omitting Overlay-only pages.
  Textures now reuse the shared composition, overlay placement, and image-effect
  pipeline. Local mode/effect changes and rejected display-mode saves update both
  native textures; Overlay-only content participates in scene availability.
  Image changes completed during failed regeneration now reach retained scenes,
  and detached windows reopened while regeneration is pending recover the last
  accepted scene on failure with current image state.
- Fixed Main's shared zoom field discarding unsubmitted Plan and 3D text when
  switching views. Drafts remain local to their view and expire on navigation,
  zoom changes, explicit commands, or loss of accepted 3D content.
- Fixed detached 3D context-menu Zoom In, Zoom Out, and Reset View targeting
  Main's camera and using Main's scene availability. These commands now reuse
  the detached window's toolbar actions and affect only its own camera.
- Fixed menu refresh re-enabling Zoom In, Zoom Out, and Reset View for an empty
  Main 3D scene, including the shared context-menu Zoom commands.
- Fixed authoritative image refresh retaining old Plan pixels and 3D page-plane
  textures when replacement content preserves both file size and modification
  time. Targeted source revisions now invalidate affected cache entries without
  hashing source files or clearing unrelated cached images.
- Fixed terminal SQL Overlay replacement/removal failures being logged without
  an operation error dialog. Rejections now use the shared error presenter;
  conflict dialogs remain owned by the collaboration coordinator.
- Fixed Main and detached Plan retaining old pixels after an image file changes
  at the same path. Surface reuse now checks the same file modification-time and
  size signature as the raster and composite caches, including effect rendering.
- Fixed returning to Takeoff restoring stale enabled Pan/Zoom actions after the
  accepted 3D scene became empty while another tab was active. Tab restoration
  projects current scene availability through the shared camera-control policy.
- Fixed Main and detached 3D camera controls retaining enabled actions and stale
  zoom text after their last geometry or page-image plane disappears. Controls
  follow accepted scene content, recover when content returns, and remain usable
  when failed regeneration preserves an accepted scene. Zoom labels round the
  actual camera percentage instead of truncating floating-point values such as
  175% to 174%.
- Fixed scale and Area presentation drift between Main and detached Plan views.
  Detached scale controls display authoritative custom scales using the shared
  formatter and clear when their page disappears. Rejected SQL Area changes
  restore the Main Area picker along with both canvases.
- Fixed nested master-data editors leaving their parents stale after closing.
  Cancelling Pay Classes retains committed deletions in the Employee picker
  without copying cancelled edits, and cancelling Cover Sheet Employee or Job
  Status pickers preserves typed and cleared parent values. Condition Type
  deletion preserves surviving selected UIDs and scroll position under filtering
  instead of selecting an unrelated or hidden row by index.
- Fixed Pay Class and Job Status editors silently omitting a new row on retry
  after a rejected save that left the row blank. Draft rows remain editable until
  saving succeeds, and inline renames immediately update active Find results.
  Condition and Condition-folder inline renames retain their authoritative
  labels when a prerequisite flush or SQL mutation is rejected; successful
  persistence projects the new name through the normal refresh.
- Fixed stale Takeoff presentation state after empty/refresh transitions. An
  editable Bid with no layers can create its first layer, active-page removal
  clears the deleted page's scale/Area controls without unloading the Bid,
  reopening a deleted detached Page disables Previous/Next until a valid Page
  becomes available, and Condition Summary refreshes retain the current surviving
  row and branch expansion. Failed layer deletion now restores the authoritative
  list and reports the correct Access or SQL operation instead of failing silently or
  presenting a generic update error. Rejected SQL Check/Uncheck All operations
  restore each layer's prior visibility. Layer dialog visibility refreshes retain
  surviving selections, the current row, and scroll position, and failed layer
  edits report one error instead of two consecutive warnings.
- Fixed remaining infrastructure callers that bypassed canonical identity and
  optional-schema contracts. Access master-data creation and import now reserve
  UIDs still named by dangling Bid, Employee, or Condition references, while SQL
  identity placeholders remain database-generated instead of being replaced by
  Access `MAX(UID)` scans. Employee saves preflight every non-null Pay Class in
  the complete batch. Condition-folder, Cover Sheet, and New Bid hierarchy
  writes now reject folder tables/parent columns unavailable in older schemas before
  changing Bid data, while flat root-folder writes remain supported.
- Fixed mutation paths that treated readable orphaned rows as writable
  solely because their stored `BidUID` looked valid. Page, Condition, Layer,
  Condition-folder, Takeoff, and typed-annotation edits and deletes now resolve
  the authoritative owning Bid before the first write. Cover Sheet saves against
  legacy schemas without optional Job Status or Employee master tables preserve
  their retained references during unrelated edits and reject explicit new
  selections instead of silently clearing or persisting them.
- Fixed writer paths that accepted valid-looking relationships without one
  authoritative owning context. Bid creation, Cover Sheet saves, status changes,
  and duplication now reject dangling Job Status and Employee-role references;
  Takeoff, annotation, Area, and selected-page creation reject orphan Bid graphs.
  New Bid resolves its complete acyclic page-folder payload independently of
  drag-produced row order. Plan paste now locks external same-bid Named View
  dependencies and clears cross-bid Hot Link targets that were not copied, so a
  matching destination UID cannot silently retarget the link.
- Fixed multi-resource mutations accepting individually valid UIDs from
  different bids. Access now preflights Takeoff inserts, assignments, bulk
  position/rotation/text saves and deletes, annotation batches, Condition
  create/update/duplicate/delete, page/folder deletes, Cover Sheet page updates,
  and bid moves before the first write. Root Layers and Condition folders require
  an authoritative Bid, and New Bid rejects page-folder references outside its
  local folder graph. SQL plan-item preflight now verifies the expected Bid, and
  queued Takeoff placement/paste includes Area and parent-Takeoff dependencies.
- Fixed alternate deletion and assignment paths bypassing canonical companion
  relationships. Condition deletion now removes `BidConditionUser` rows, and
  Page, Condition, and Bid-level cascades remove line/arrow/dimension records
  linked through either takeoff endpoint. Named View deletion rejects an
  incomplete batch that omits dependent Hot Links. Project deletion clears
  deleted-bid restore pointers, and bid moves reject missing original projects.
  Annotation creation now validates its same-bid Page, optional Layer, and Hot
  Link target before allocation, while page-area selection rejects an Area from
  another bid.
- Fixed malformed Bid Area parent graphs silently disappearing from the Area
  editor and picker. Reload, save, Duplicate Bid, and OST/OSP import now enforce
  a same-bid acyclic area forest before mutation, zero parents reconstruct as
  roots, and flat writes remain
  compatible with legacy schemas lacking `ParentUID`. Deleting a page now also
  clears surviving same-bid Master Page and cross-page comment-parent pointers
  to records removed by that deletion. Direct, Page, and Condition takeoff
  deletion now clear all surviving parent and typical takeoff self-links instead
  of leaving records that later fail reload, import, or duplication integrity.
- Fixed malformed Project, Bid, takeoff, Named View, Hot Link, and other typed
  annotation UIDs being reconstructed by cursor order or mutated as a group.
  Project/Bid hierarchy loading, singular Access mutations, Duplicate Bid, and
  OST/OSP import now reject invalid or duplicate physical identities before any
  write or cascade. Bid moves reject a missing Project target, and bid loading
  rejects takeoffs whose required Page, Condition, or non-root Takeoff parent is
  absent, cross-bid, or part of a parent cycle. Duplicate Bid now rejects copied
  internal references that are dangling or cross-bid before allocating new UIDs,
  preventing malformed Hot Links, layers, folders, and other optional references
  from silently binding to unrelated destination records after an ID collision.
- Fixed cyclic Condition-folder and Page-folder graphs disappearing from normal
  hierarchy and Cover Sheet reconstruction. Reload, Duplicate Bid, and OST/OSP
  import now reject cycles deterministically; pre-existing missing parents
  remain root-level compatibility items. Folder/page mutations validate exact
  same-bid parents before writing, and deleting a Condition folder reparents its
  surviving child folders to the root. Access creation, duplication, and import
  now allocate Projects, Bids, pages, Conditions, areas, layers, folders,
  takeoffs, and annotations above canonical dangling inbound references so old
  orphan rows cannot silently attach to newly created owners through UID reuse.
- Fixed loaded bids discarding their authoritative Job Status UID and later
  using duplicate display names for lock checks, Project Tree status actions,
  and status grouping. Remote master-data projection now refreshes hierarchy
  labels and active-bid locking, Condition Type renames refresh cached Condition
  labels by UID, and Employee deletion/use checks cover every direct bid role.
  Employee deletion also follows the schema-defined global Employee identity
  when removing DPC subscribers, preventing both orphaning and UID-collision
  over-deletion.
- Fixed malformed master-data tables with duplicate physical UIDs being
  reconstructed by cursor order or updated as a group. Condition Types, Job
  Statuses, Employees, Pay Classes, and Access Levels now reject duplicate
  authoritative UIDs before reconstruction, import reconciliation, or mutation.
- Fixed malformed bid-owned layers, folders, pages, Conditions, areas, typical
  areas, and zones with duplicate, null, zero, or nonnumeric UIDs reaching
  reconstruction, import, or Duplicate Bid. Access now preflights singular
  page, Condition, layer, folder, and area mutations before any update or
  cascade, preventing one action from changing multiple corrupt physical rows.
- Fixed OST/OSP master-data reconciliation and editors so duplicate display
  names or employee keys cannot silently bind imported bids, Cover Sheet fields,
  Employees, or Conditions to an arbitrary same-label master record.
- Fixed bid creation, import, and Duplicate Bid reusing bid number 1 when a
  readable legacy MDB lacked the durable `Settings.NextBidNo` allocator. Those
  write paths now reject the unsupported writable schema without modifying the
  bid graph. Clearing a page's area filter now preserves inactive
  `BidPageSettings` records, while save and Duplicate Bid normalize malformed
  competing selected rows, including duplicate physical UIDs. Duplicate Bid
  also remaps area and typical-area ownership for legacy page-setting tables
  that have no row UID.
- Fixed global `Settings` rows being selected nondeterministically and updated
  as a group when malformed duplicates existed. Empty Settings tables now
  persist the first bid-number allocation, sequence-write failures abort import,
  and MDB/SQL normalize the zero sequence consistently. SQL now rejects missing,
  duplicated, or wrong-incarnation `DatabaseMetadata` at every identity consumer.
  Duplicate selected page-area rows reconstruct and normalize with the existing
  import/export precedence, and Duplicate Bid clears a known page-typed Cover
  Sheet selector when its referenced source page is missing.
- Fixed malformed bids with multiple `BidSettings` rows being loaded
  nondeterministically, updated as a group, imported, or multiplied by Duplicate
  Bid. Duplicate Bid also remaps the known page-based Cover Sheet selection, and
  Cover Sheet nested pickers now restore duplicate-named statuses and employees
  by UID instead of display text. Duplicated bids now receive their own creation
  timestamp, and deleting a page clears only Cover Sheet selectors whose type is
  page.
- Fixed Duplicate Bid copying bid-employee assignments twice, reusing source
  GUIDs, and leaving ancillary labor, total, typical-group, Boost, and DPC rows
  linked to source-bid entities. Page, Condition, and area deletion now removes
  every schema-declared ancillary dependent before deleting its owner.
- Fixed Duplicate Bid regenerating takeoff, annotation, comment, folder, page,
  and area identities without reconstructing all references between the copied
  rows. The duplicate now owns an independent reference graph, including
  takeoff parent/annotation attachments and typical-area counts, and SQL OST/OSP
  import now resolves takeoff `ParentUID` through the generated SQL identities.
- Fixed persisted Conditions with no layer reloading with the literal layer UID
  `"None"`, and fixed Plan clipboard snapshots losing current takeoff label-font
  state by retaining stale raw extras after the source was edited.
- Fixed delayed SQL Plan leases and mutation completions accepting a deleted and
  recreated page solely because its UID matched. Main and detached Plan
  geometry, properties, deletion, insertion, placement selection, preview
  restoration, and undo attachment now retain the authoritative page instance;
  failed mutations also cannot restore editable previews after access is
  revoked. Active takeoff placement similarly exits when one of its captured
  Conditions is authoritatively replaced with the same UID, and a placement
  suspended by layer visibility can no longer resume against a replacement
  Condition or Bid.
- Fixed a hidden detached 3D surface resuming its native renderer when a pending
  scene, texture, or failed same-scene refresh completed. Explicit MDB reload now
  closes routed read and write handles to the previous database file at the same
  path, retains ownership when a close fails, and reports that failure so cleanup
  can retry.
- Fixed delayed SQL Condition, folder, layer, bid-delete, and project-delete UI
  follow-ups applying placement, selection, inline-edit, or navigation state to
  a newly loaded authoritative Bid or Project that reused the original UID.
  Placement-producing completions also revalidate current edit access.
- Fixed Condition Tree and Project Tree keyboard commands competing with shared
  Plan shortcuts, Condition context creation losing its right-clicked folder,
  and tree context submenus losing their Qt ownership before execution. Nested
  Condition/page confirmations and native page dialogs now revalidate their
  captured authoritative target and edit access before writing. Project Tree
  drag indicators now use the same exact source/destination authorization as
  the eventual bid move.
- Fixed Duplicate from a Project Tree context menu acting on the previously
  active bid when the user right-clicked a different bid in a multi-selection.
  Toolbar and Ctrl+D duplication remain singular active-bid actions.
- Fixed Project Tree Close, Import, New, Delete, Rename, and Job Status context
  actions checking or mutating the active database instead of their captured
  right-click target. Export and Renumber are now disabled when the context bid
  is not the loaded active bid, and selection-wide Delete/Paste authorization
  checks every captured database/resource rather than only the active one.
- Fixed native 3D context menus transient-parenting themselves to the embedded
  render surface instead of its real top-level window, which caused Qt
  `QWidgetWindow ... must be a top level window` warnings.
- Fixed bid duplication probing nonexistent `BidLayerUID` columns and leaving
  copied comments linked to the source bid's layers. Layer references now use
  the shared MDB/SQL schema contract.
- Fixed deleting an Overlay Only page's overlay from Cover Sheet leaving the
  original image unavailable from Plan View; overlay deletion now selects the
  original image and clears all saved overlay placement and rotation data, and
  Cover Sheet display choices now stay consistent with the images present.
- Fixed Condition edits, including Element elevation changes, blanking and
  rebuilding the active 3D view through a database-wide refresh. Native mesh
  changes now regenerate behind the visible scene, while non-3D Condition
  properties and Condition Type catalog edits no longer rebuild Plan or 3D views.
- Fixed SQL Condition Properties, Cover Sheet/New Project nested editors, and
  page-setting dialogs failing to preserve authoritative collaboration ownership
  through save, retry, Apply-to-All, and record navigation. Delayed modal grants
  and Plan mutation completions can no longer open or restore stale selections,
  previews, properties, or tools after the user changes database, bid, or page;
  reconnects also invalidate old modal and Plan leases and reject projections,
  presence, locks, or status callbacks from the previous SQL session. Delayed
  hierarchy and Condition completions likewise preserve newer navigation,
  selection, placement, and toolbar state. Recovered mutation completions now
  remain bound to the exact replacement session, and startup imports, modal
  saves, Plan scale controls, and debounced page display settings wait for the
  final recovered outcome instead of treating queue acceptance or an
  intermediate recovery state as completion. Failed visual settings restore
  only their still-current page or bid, stale workspace selections fall back to
  their loaded database, authoritative page/layer refreshes invalidate older
  visual-setting callbacks, local completions preserve newer pending visual
  values across Main and detached Plan projections, and cleared undo history
  ignores late completions. Tentative application shutdown now holds queued
  startup loading, project imports, database creation results, detached-workspace
  restoration, and update checks until shutdown either succeeds or aborts;
  aborted closes resume deferred persistence and replay valid work once in causal
  order, while terminal shutdown invalidates it along with stale license
  callbacks and post-import refresh work. Configured application services now
  shut down after startup failure or an unexpected event-loop exit, and open
  License, Update, Open Files, SQL database, nested Cover Sheet/master-data,
  New Project, page-setting, named-view, color/font, database-prompt, and
  import/export progress dialogs do not resume into released UI/service state
  when their parent closes or their page/selection target changes. Dialog-owned
  asynchronous saves, queued view/toolbar callbacks, and realtime notifications
  also discard stale Qt ownership. Cleanup attempts every owned UI stage,
  workspace-state binding, subscription, and license worker even when an earlier
  teardown step fails, retains
  transiently failed subscriptions and worker waits for retry, and cannot finish
  before an accepted worker starts; EventBus delivery also skips subscriptions
  removed or replaced during the same publication, including recursive delivery,
  and late navigation cancellation preserves the worker stop request.
- Fixed structural Condition and layer changes leaving multi-Condition placement
  active after a primary or secondary Condition became hidden, unavailable, or
  incompatible with the active placement geometry.
- Fixed authoritative Condition updates and folder-only projections discarding
  otherwise valid Takeoff placement after reconstructing Condition objects.
  Layer visibility now suspends and restores the complete multi-Condition tool
  owner set, while same-UID replacement, access loss, and newer tool choices
  still invalidate restoration. Passive Condition Tree rebuilds retain the
  focused row, and toolbar Takeoff availability follows that exact active row.
- Fixed PDF, 3D-format, and Summary CSV exports continuing with a different bid
  when navigation changed while the native destination dialog was open.
- Fixed concurrent deletion of one member of a queued bulk move or reassignment
  being reported as a partial success.
- Fixed native overlay/import/export dialog continuations writing after their
  page, bid, or owning window changed; authoritative page replacement now drops
  matching deferred page settings without discarding unrelated writes. Detached
  Plan now preserves local undo history while clearing it for remote structural
  changes, and external Access refreshes cancel stale Plan interactions,
  selection, and undo state only in the refreshed active database. Main and
  detached Plan navigation and authoritative structural projections now cancel
  active gestures, selection boxes, previews, and geometry leases before stale
  interaction state can cross contexts, and remotely deleted area selections
  are cleared immediately. Edit-access loss also releases pending or granted
  geometry leases, including grants that arrive after a Main or detached page
  retarget. Remote annotation updates now cancel and refresh only their affected
  pages when page ownership is authoritative and preserve unrelated detached-page
  undo history; deleted or replaced named views cannot retain stale navigation
  targets, and late SQL annotation completions cannot reactivate tools after the
  page or edit access changes or attach old-bid undo commands to the newly active
  bid.
- Fixed restart/reconnect accepting a SQL database recreated under the same
  server/name as the saved database, and fixed import/export continuations
  accepting replacement projects or bids that reused the captured UID while a
  native file dialog was open.
- Fixed hierarchy, Summary, Plan, and 3D context actions applying to rebuilt
  same-UID rows, replaced scenes, changed selections, or revoked edit access.
  Tree resets now cancel active drags and inline editors, 3D scene replacement
  cancels pointer/context actions and camera inertia begun on prior geometry,
  hidden or retargeted 3D surfaces cannot retain native camera motion, and page
  or project-tree rebuilds cannot activate replacement rows from earlier mouse
  presses. Authoritative project deletion now projects the tree's database-root
  fallback into action state, while revoked access cancels provisional layer
  creation and prevents inline Condition, folder, or layer names from remaining
  changed without persistence. Condition and bid paste drop remotely deleted
  source rows, reference clipboards are invalidated when their database unloads,
  and late cut completions cannot clear newer clipboard work. Main and detached
  Plan clipboards recognize equivalent Windows paths for the same database.
  Delayed paste results no longer replace a newer selection or restore cleared
  handles after navigation, another paste, or a rejected save; uninterrupted
  pastes retain their normal result selection and rollback behavior.
  Geometry/property-save and delete completions likewise preserve newer Main
  and detached selections, including after Undo/Redo, while authoritative
  rollback and history recording still complete. Annotation insertion respects
  newer selection or tool intent and does not reactivate its old tool over that
  intent, even when selection stays unchanged or empty. Annotation-only
  selection, deletion, and recovery immediately update Main Copy, Delete, and
  Duplicate actions.
  Mixed annotation paste/delete history, SQL import and recovery correlation,
  dirty previews, selection, and pending completion state now keep table-scoped
  annotation IDs distinct by type across Main and detached Plan rebuilds.
  Pending 3D edit state is scoped to its originating database, and Plan hot-link
  hit testing uses collision-safe scene identity when another entity shares its
  stored UID.

## 1.2.6.1 - 2026-08-19

### Changed

- SQL database creation opens **Database Properties (SQL Server)** directly for
  server, authentication, and database-name entry. As with finding an existing
  database, the selected Windows or SQL login is used for normal access. Creation requests
  separate temporary creator credentials when submitted. Setup runs with progress
  and verifies runtime permissions before registration;
  completion waits for healthy opening, recognizes completion at the timeout
  boundary, and discards setup results after dialog cleanup. Both SQL dialogs fit their contents and
  expose certificate settings directly, without duplicate application-user fields.

- Layout-sized dialogs now keep their established widths while deriving fixed
  heights from their current controls, spacing, padding, text wrapping, and
  system fonts.
  Cover Sheet opens at its natural layout size initially, remembers later user
  resizing and maximized or windowed state, and provides maximize and close
  controls. Condition Types, Employees, Layers, Open Files, Bid Areas, Job
  Statuses, and Payroll Classes retain their configured initial sizes and also
  remember their resized and maximized or windowed state.
