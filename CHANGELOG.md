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
  selection, placement, and toolbar state.

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
