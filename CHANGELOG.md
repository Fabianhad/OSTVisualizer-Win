# Changelog

## Unreleased

### Added

- Added persistent PDF annotation caption options with a global enable switch and Bluebeam-compatible selection, ordering, units, and formatting for all captions supported by exported polygon measurements.
- Added four-row takeoff elevation callouts with condition name, top and bottom elevations, cubic-yard quantity, and condition/layer/area visibility controls to the 2D plan view in single-file HTML exports.
- Added a read-only MCP bid comparison tool that matches conditions by reference number, ignores insignificant floating-point quantity noise, and returns bounded condition-type aggregates for metadata, quantities, takeoff counts, and changed pages.

### Changed

- Changed Cover Sheet commits to perform a single post-save database refresh, reducing UI stalls after large page deletion batches.
- Changed OST/OSP exports to emit bid layers in ascending sequence order for closer compatibility with original On-Screen Takeoff exports.
- Updated the main window title to show the selected database and bid alongside the OST Visualizer app name.

### Fixed

- Fixed OST imports failing on safely recoverable references by skipping orphaned hole/backout takeoffs and clearing stale selected-page or annotation takeoff attachments while continuing to reject other invalid database references.
- Fixed project-file imports so an existing active bid remains visually selected after importing into its folder, and Import remains available from the Summary tab whenever the current context permits importing.
- Fixed plan pages with both original and overlay images so hiding the image layer immediately reveals the white page canvas without an unexpected fit-to-page jump.
- Fixed takeoff clicks after condition sidebar reloads so the clicked takeoff's condition is reselected and highlighted when the previous highlight was cleared.
- Fixed OSP exports so the embedded OST keeps the drawing paths stored in the database instead of package-internal `TempImages!.tmp` paths.
- Fixed the Select Named View dialog so refocusing a non-empty search field shows the current matching named views again.
