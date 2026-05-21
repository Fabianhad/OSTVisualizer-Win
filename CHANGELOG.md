# Changelog

## 1.2.3 - Unreleased

### Added
- Added an optional read-only local MCP server for project, bid, page, condition, takeoff, quantity, selected-context, and scope-review context.
- Added a local read-only MCP bridge for live desktop context such as active view, selected pages, highlighted conditions, and selected takeoffs.
- Added a Tools menu MCP setup dialog for copying Claude Desktop/Cursor config and Codex setup commands.

### Changed
- Replaced the external MCP runtime dependency with an internal stdlib stdio adapter, and removed obsolete MCP dependency/setup files.
- Limited MCP database access to checked OST Visualizer database settings, with bounded responses and status/result-limit metadata.
- Build scripts now produce a separate lightweight Nuitka standalone MCP helper directory instead of combining MCP hosting with the desktop executable.
- Kept MCP read-only: no database path overrides, exports, CSV, writes, shell execution, arbitrary SQL, PDF text extraction, OCR, or page text tools are exposed.

### Fixed
- Included the standalone `ostv-mcp.exe` helper and its runtime files in the desktop distribution so production MCP client config points to an installed executable.
- Tightened MCP JSON-RPC request validation and removed an arbitrary hierarchy fallback for unmatched database files.
