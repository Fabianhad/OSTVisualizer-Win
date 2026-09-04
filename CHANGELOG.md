# Changelog

## Unreleased

### Fixed

- Fixed loaded bids discarding their authoritative Job Status UID and later
  using duplicate display names for lock checks, Project Tree status actions,
  and status grouping. Remote master-data projection now refreshes hierarchy
  labels and active-bid locking, Condition Type renames refresh cached Condition
  labels by UID, and Employee deletion/use checks cover every direct bid role.
  Employee deletion also follows `BidEmployees` identity when removing DPC
  subscribers, preventing orphaned subscriber rows when the two UIDs differ.
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
  as a group when malformed duplicates existed. Empty legacy settings tables now
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
  Mixed annotation paste/delete history, SQL import and recovery correlation,
  dirty previews, selection, and pending completion state now keep table-scoped
  annotation IDs distinct by type across Main and detached Plan rebuilds.
  Pending 3D edit state is scoped to its originating database, and Plan hot-link
  hit testing uses collision-safe scene identity when another entity shares its
  stored UID.

## 1.2.6.1 - 2026-08-19

### Changed

- Layout-sized dialogs now keep their established widths while deriving fixed
  heights from their current controls, spacing, padding, text wrapping, and
  system fonts.
  Cover Sheet opens at its natural layout size initially, remembers later user
  resizing and maximized or windowed state, and provides maximize and close
  controls. Condition Types, Employees, Layers, Open Files, Bid Areas, Job
  Statuses, and Payroll Classes retain their configured initial sizes and also
  remember their resized and maximized or windowed state.
