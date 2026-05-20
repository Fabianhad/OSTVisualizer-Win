# Changelog

## 1.2.2.4 - Unreleased

### Added
- Added an optional read-only local MCP server for project, page, condition, takeoff, and quantity context.
- Added a local read-only MCP bridge for live desktop context such as active view, selected pages, highlighted conditions, and selected takeoffs.
- Added read-only MCP estimator tools for condition summaries, selected-takeoff summaries, condition search, and empty page/condition checks.
- Added a read-only MCP selected-pages summary tool for the pages currently driving the 3D mesh view.
- Added setup guidance for MCP-compatible clients using the standalone stdio server.
- Added a Tools menu MCP setup dialog for copying Claude Desktop/Cursor config and Codex setup commands.

### Changed
- Limited MCP database access to OST Visualizer's checked database settings instead of accepting explicit database path arguments.
- Deferred MCP CSV export until the app has a polished CSV export path.
- Build scripts now produce a separate lightweight one-file `ostv-mcp.exe` helper instead of combining MCP hosting with the desktop executable.
- Removed the MCP helper's Qt runtime dependency from live-context bridge reads.
