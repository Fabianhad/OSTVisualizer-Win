# Changelog

## 1.2.3 - Unreleased

### Added
- Added a first-pass OST-style Options dialog with persisted roping, page label, hotlink target, and toolbar text preferences.
- Added takeoff color mode and grayscale controls to the Options dialog while keeping menu quick actions on the shared app-config path.
- Added an optional read-only local MCP server for project, bid, page, condition, takeoff, quantity, selected-context, and scope-review context.
- Added a local read-only MCP bridge for live desktop context such as active view, selected pages, highlighted conditions, and selected takeoffs.
- Added MCP setup controls to the Options dialog for copying Claude Desktop/Cursor config and Codex setup commands.
- Added read-only MCP area context with area names on takeoffs/current context plus `list_areas` and `get_area_summary`.
- Added separate Options controls for grid, PDF-line, takeoff, and right-angle snap thresholds.

### Changed
- Moved MCP setup out of its standalone Tools menu dialog and into the Options dialog.
- Replaced the external MCP runtime dependency with an internal stdlib stdio adapter, and removed obsolete MCP dependency/setup files.
- Limited MCP database access to checked OST Visualizer database settings, with bounded responses and status/result-limit metadata.
- Build scripts now produce a separate lightweight Nuitka standalone MCP helper directory instead of combining MCP hosting with the desktop executable.
- Kept MCP read-only: no database path overrides, exports, CSV, writes, shell execution, arbitrary SQL, PDF text extraction, OCR, or page text tools are exposed.
- Split placement snapping so takeoff, PDF-line, and grid snapping use independent app-config toggles and thresholds.
- Simplified Edit Condition advanced properties by hiding compatibility-only Connect/Snap fields and wiring visible display, pattern, grid, trim, and rounding behavior.
- Text annotations now reuse the text-format toolbar and support inline editing with persisted text/style updates.
- Removed the obsolete `BidConditions.NameFont*` condition-label formatting path; generated label styles now use only `BidTakeoffs`.

### Fixed
- Included the standalone `ostv-mcp.exe` helper and its runtime files in the desktop distribution so production MCP client config points to an installed executable.
- Tightened MCP JSON-RPC request validation and removed an arbitrary hierarchy fallback for unmatched database files.
- Fixed Intelligent Paste so copied takeoffs paste at the cursor, support temporary original-axis snap guides only during the first drag, and stop using that snap state after release or cancel.
- Routed text-annotation inline-edit keyboard shortcuts and arrow keys to the active text editor instead of plan-view selection/move commands.
- Fixed text annotation selected/edit outlines to use the real textbox resize bounds and clipped overflowing text to the textbox.
- Centered area Display Dimension labels inside the takeoff while keeping Display Name labels below the takeoff.
- Cleared stale condition text label selection outlines when selecting another label or text annotation.
- Kept text annotation textbox resizing centered when font, style, or text edits change the box size.
- Updated the shared text-format toolbar with formatting icons and a live text-color swatch.
- Fixed text annotation style and autosized textbox updates so overlay refreshes keep the new formatting and centered box.
- Fixed condition Display Name/Dimension label formatting so supported font style fields persist through overlay rebuilds instead of resetting after takeoff refreshes.
- Fixed condition Display Name/Dimension label formatting so label boxes recompute immediately after toolbar style changes.
- Stored generated condition label formatting on `BidTakeoffs`, using `Font*` for Display Dimension labels and `NameFont*` for Display Name labels.
- Placed area Display Name labels at the centroid when no dimension label is shown, or below the centered dimension label when both are enabled.
- Kept the text-format toolbar open after formatting generated Display Name and Display Dimension labels across overlay refreshes.
- Added rename-only inline editing for named view labels without showing the text-format toolbar.
- Fixed named view renames so `BidNamedViews.Name` is written as plain text instead of text-annotation encoded bytes.
