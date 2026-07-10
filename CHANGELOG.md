# Changelog

## 1.2.4.3 - Unreleased

### Added

- Native 3D views can now show the active page image plane beneath the generated model using the existing page image layer visibility.

### Changed

- MCP tool and resource responses now summarize oversized inline output and save the full result under app-data MCP output files, returning local file references until downloadable attachments are supported.

### Fixed

- Fixed double-click startup imports for `.ost` and `.osp` files so the splash screen closes, the progress dialog is shown during import, and Deleted Bids targets import as orphaned.
- Fixed `.osp` imports from packages whose page image paths point to legacy absolute OST folders while the drawing files are embedded in the package, with warnings for missing or ambiguous embedded image matches.
- Fixed takeoff and annotation undo/redo position restores after page scale changes so edited geometry stays visually consistent.
- Fixed page-scale rescaling so text annotation positions remain valid coordinate strings instead of being written as binary data.
