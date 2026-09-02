# Changelog

## Unreleased

### Fixed

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
  visual-setting callbacks, and cleared undo history ignores late completions.
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
  Plan also clears stale undo history when its bid is removed remotely.
- Fixed restart/reconnect accepting a SQL database recreated under the same
  server/name as the saved database, and fixed import/export continuations
  accepting replacement projects or bids that reused the captured UID while a
  native file dialog was open.

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
