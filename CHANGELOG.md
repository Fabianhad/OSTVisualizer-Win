# Changelog

## 1.2.3 - Unreleased

### Added
- Added a first-pass OST-style Options dialog with persisted roping, page label, hotlink target, and Cover Sheet toolbar text preferences.
- Added takeoff color mode and grayscale controls to the Options dialog while keeping menu quick actions on the shared app-config path.
- Added an optional read-only local MCP server for project, bid, page, condition, takeoff, quantity, selected-context, and scope-review context.
- Added a local read-only MCP bridge for live desktop context such as active view, selected pages, highlighted conditions, and selected takeoffs.
- Added MCP setup controls to the Options dialog for copying Claude Desktop/Cursor config and Codex setup commands.
- Added read-only MCP area context with area names on takeoffs/current context plus `list_areas` and `get_area_summary`.
- Added safe read-only MCP page search, layer summaries, named views, hotlinks, redacted page sheet metadata, bounded PDF text/vector summaries, page markup summaries, overlay summaries, and page-scoped PDF text search.
- Added read-only MCP prompt workflows for bid scope review, page QA, markup/link review, overlay/PDF context, and quantity variance review.
- Added separate Options controls for grid, PDF-line, takeoff, and right-angle snap thresholds.
- Added a Reset All Settings button to the Options dialog that restores app preferences and workspace layout state to defaults.
- Added embedded PDF text selection in the plan view with I-beam hover, drag-range highlighting, and copy support.
- Added 2D rendering, toolbar placement, and Bluebeam-style PDF LineDimension export for BidDimensions annotations, including end ticks, feet/inches labels, text-label formatting, measurement metadata, and corrected PDF appearance bounds.
- Added a Move Overlay Image toolbar action with separated red/base and blue/overlay live preview, preserving OST `OverlayRect` placement for PlanView and PDF export.

### Changed
- Moved MCP setup out of its standalone Tools menu dialog and into the Options dialog.
- Replaced the external MCP runtime dependency with an internal stdlib stdio adapter, and removed obsolete MCP dependency/setup files.
- Limited MCP database access to checked OST Visualizer database settings, with redacted local paths plus bounded responses and status/result-limit metadata.
- Build scripts now produce a separate lightweight Nuitka standalone MCP helper directory instead of combining MCP hosting with the desktop executable.
- Kept MCP read-only: no database path overrides, exports, CSV, writes, shell execution, arbitrary SQL, PDF rendering, OCR, unbounded page text dumps, or database mutation are exposed.
- Split placement snapping so takeoff, PDF-line, and grid snapping use independent app-config toggles and thresholds.
- Simplified Edit Condition advanced properties by hiding compatibility-only Connect/Snap fields and wiring visible display, pattern, grid, trim, and rounding behavior.
- Text annotations now reuse the text-format toolbar and support inline editing with persisted text/style updates.
- Removed the obsolete `BidConditions.NameFont*` condition-label formatting path; generated label styles now use only `BidTakeoffs`.
- Removed the misleading Options preference for auto dimension lines; Display Dimension remains a per-condition setting.
- Enabled the Options `Main` hotlink target so hotlinks can navigate the main takeoff view to the target page and named-view zoom instead of opening a detached window.
- Adjusted hotlink selection so clicks activate hotlinks while rubber-band selection controls move selection, including moving selected hotlinks.
- Matched menu-opened Employees, Bid Areas, Condition Types, and Payroll Classes dialogs to the OK-only master-data dialog button layout.
- Replaced the separate right-angle indicator preference with the `Snap to right angle` Snap Settings option and threshold while preserving configured mouse angle snapping.
- Changed the default Options settings to show Cover Sheet toolbar text, use original takeoff colors, keep grayscale off, and enable snap to right angle.
- Updated Cover Sheet image path cells to show filenames by default, edit full paths on double-click, and highlight missing image files.
- Improved composite page rendering by preserving antialias coverage when tinting layered images.
- Prioritized enabled overlay PDF layers for composite/overlay PDF snapping and embedded text selection, with overlay-only PDF rendering using dynamic base and tile refresh.
- PDF export now follows enabled page image layers, exporting overlay-only pages directly from the overlay source and main+overlay pages as a flattened red/blue comparison background with annotations on top.
- Improved native PDF export for line, arrow, shape, ink, and text annotations to better match Bluebeam/Revu markups, render line-based appearances correctly on first open, and keep exported text boxes wrapped inside their textbox bounds.
- Linear takeoff line patterns now rotate with the takeoff direction so horizontal, vertical, and diagonal hatches follow the line instead of the page axes.

### Fixed
- Fixed several stale UI state and failed-write rollback paths, including 2D placement staying active in 3D, failed bid switches clearing the current workspace/undo owner, stale condition and area selections after rebuilds, detached page windows showing deleted or failed-load content, page/layer/overlay controls drifting after save failures, and batched condition/curve updates refreshing once instead of reentering mid-command.
- Preserved unsaved takeoff moves during same-page overlay refreshes, rolled back failed plan-view and detached annotation edits, made master-data window close/cancel paths discard pending edits instead of saving them, tightened Bid Area save/refresh failure handling, and distinguished saved-but-refresh-failed project creation from plain save failure.
- Included the standalone `ostv-mcp.exe` helper and its runtime files in the desktop distribution so production MCP client config points to an installed executable.
- Kept the UI responsive while creating new databases by running database creation through the existing progress dialog workflow.
- Tightened MCP JSON-RPC request validation and removed an arbitrary hierarchy fallback for unmatched database files.
- Fixed Intelligent Paste so copied takeoffs and annotations paste at the cursor, support temporary original-axis snap guides only during the first drag, and stop using that snap state after release or cancel.
- Fixed Cover Sheet page image paths so saved `BidPages.ImagePath` values use Windows backslashes for OST compatibility.
- Fixed plan-view crashes when toggling original/overlay image visibility after image graphics items had already been cleared.
- Fixed overlay image placement to honor OST `OverlayRect` alignment values when displaying and exporting red/blue overlays.
- Replaced high-resolution PDF tile refresh with visible-frame PDFium offset rendering and buffered cache replacement to avoid blurry, distorted, or blank zoomed PDF overlay views.
- Fixed saved page view positions to round-trip OST `CurrentX`/`CurrentY` values as 96-DPI page pixels.
- Fixed PDF export so hidden takeoff/annotation layers stay hidden and OST numeric text alignment exports as left, center, or right.
- Fixed PDF export default filenames so page names that already end in `.pdf` do not produce `.pdf.pdf`.
- Cleared stale detached page-window, PDF renderer, export background, and MCP bridge references during cleanup, and bounded PDF metadata caches across page/file switches.
- Routed text-annotation inline-edit keyboard shortcuts and arrow keys to the active text editor instead of plan-view selection/move commands.
- Fixed text annotation selected/edit outlines to use the real textbox resize bounds and clipped overflowing text to the textbox.
- Centered area Display Dimension labels inside the takeoff while keeping Display Name labels below the takeoff.
- Cleared stale condition text label selection outlines when selecting another label or text annotation.
- Kept text annotation textbox resizing centered when font or style changes resize the box, while inline text edits preserve the existing textbox bounds, wrapping, and editor selection state.
- Updated the shared text-format toolbar with formatting icons and a live text-color swatch.
- Fixed text annotation style and autosized textbox updates so overlay refreshes keep the new formatting and centered box.
- Fixed condition Display Name/Dimension label formatting so supported font style fields persist through overlay rebuilds instead of resetting after takeoff refreshes.
- Fixed condition Display Name/Dimension label formatting so label boxes recompute immediately after toolbar style changes.
- Stored generated condition label formatting on `BidTakeoffs`, using `Font*` for Display Dimension labels and `NameFont*` for Display Name labels.
- Placed area Display Name labels at the centroid when no dimension label is shown, or below the centered dimension label when both are enabled.
- Kept the text-format toolbar open after formatting generated Display Name and Display Dimension labels across overlay refreshes.
- Added rename-only inline editing for named view labels without showing the text-format toolbar.
- Fixed named view renames so `BidNamedViews.Name` is written as plain text instead of text-annotation encoded bytes.
- Refreshed detached annotation/view window named-view combo boxes immediately after named view renames.
- Fixed placement live previews so disabling full-window crosshairs no longer disables mouse tracking needed for preview updates.
- Fixed holes-only paste so copied backout holes enter paste-backout placement even when Intelligent Paste is disabled.
- Kept project tree folders expanded after deleting a bid when the folder was opened by restored selection state.
- Displayed bids without an assigned job status as `(unassigned)` in the project tree Status column.
