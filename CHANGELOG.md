# Changelog

## 1.2.3 - Unreleased

### Added
- Added an optional read-only local MCP server for project, page, condition, takeoff, and quantity context.
- Added a local read-only MCP bridge for live desktop context such as active view, selected pages, highlighted conditions, and selected takeoffs.
- Added read-only MCP estimator tools for condition summaries, selected-takeoff summaries, condition search, and empty page/condition checks.
- Added a read-only MCP selected-pages summary tool for the pages currently driving the 3D mesh view.
- Added setup guidance for MCP-compatible clients using the standalone stdio server.
- Added a Tools menu MCP setup dialog for copying Claude Desktop/Cursor config and Codex setup commands.
- Added bounded read-only MCP review tools for bid quantity summaries, scope gaps, duplicate condition names, zero-quantity conditions, unplaced takeoffs, and page context.

### Changed
- Limited MCP database access to OST Visualizer's checked database settings instead of accepting explicit database path arguments.
- Added status and result-limit metadata to MCP responses for safer client handling.
- Deferred MCP CSV export until the app has a polished CSV export path.
- Replaced the external MCP runtime dependency with an internal stdlib stdio adapter for the current local read-only MCP scope.
- Removed obsolete MCP dependency and source setup files now that the internal stdlib server is the production path.
- Build scripts now produce a separate lightweight Nuitka standalone MCP helper directory instead of a one-file helper or combining MCP hosting with the desktop executable.
- Removed the MCP helper's Qt runtime dependency from live-context bridge reads.

### Fixed
- Included the standalone `ostv-mcp.exe` helper and its runtime files in the desktop distribution so production MCP client config points to an installed executable.
