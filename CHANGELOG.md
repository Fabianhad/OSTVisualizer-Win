# Changelog

## 1.2.6 - 2026-08-19

### Added

- Added a required Windows activation audit identity so license activations
  record the initiating `DOMAIN\User`, computer name, and domain/workgroup join
  context without incorporating mutable account or network names into the HWID.

### Fixed

- Fixed machine license identities changing when WMIC, WMI results, user-profile
  files, or unrelated devices changed. The canonical HWID v1 pins one SMBIOS
  System UUID or machine-scoped installation UUID, uses a full SHA-256 value,
  fails explicitly when the pinned identity is unavailable, and clears invalid
  local license caches for reactivation. Firmware API failures now retain the
  Windows error details in diagnostics, and server rejection of a generated
  HWID is reported separately from local hardware-identity unavailability.
- Fixed grid-snapped multi-item moves changing the spacing between selected
  objects when their original positions had different grid offsets; drag
  previews, committed Access and SQL moves, and undo/redo now apply one shared
  snapped group translation.
- Fixed flipped curved Linear takeoffs retaining the original signed curve
  offset, which could put the curve on the wrong side and shift a subsequent
  mixed-selection rotation.
- Fixed active-page restoration being able to skip the bid-active navigation
  stage and log an invalid-transition warning after a file or bid context change.
- Fixed repeated Select All or current-area selection commands leaving only the
  previously active condition highlighted when the selected takeoff IDs had not
  changed; the Conditions sidebar now reprojects every represented condition.