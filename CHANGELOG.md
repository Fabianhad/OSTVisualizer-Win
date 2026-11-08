# Changelog

## 1.3.1 - Unreleased

### Added

- **Folder checkboxes in the page list.** Folders in the page drop-down now
  have a checkbox that checks or unchecks every page inside them, including
  pages in subfolders. A folder shows a partial check while only some of its
  pages are checked, and clicking it then checks them all. The page selection
  updates once per click, and folders without pages have no checkbox.

### Fixed

- **Annotation tools survive a page switch.** Switching pages while the Text,
  Dimension or Hotlink tool was active no longer drops back to the Select
  cursor; the tool stays active on the new page, as the Takeoff, Pan and Zoom
  tools already did.
- **Cancelling the hotlink dialog keeps the Hotlink tool.** Cancelling the
  named view picker that opens when you place a hotlink now returns to the
  Hotlink cursor instead of the Select cursor, in the main plan and in
  detached page windows.
- **The last page of a bid is no longer overwritten by the first page.** When a bid
  opened on its first page because its saved page could not be read, that first
  page was then saved as the bid's page, so the real last page was lost for good.
  A page the app picks on its own is no longer saved; only a page you pick is.
- **A takeoff's condition stays selected when you switch pages.** Clicking a
  takeoff highlights its condition in the Conditions sidebar, and that
  selection is no longer cleared by switching pages, so you no longer have to
  pick the Takeoff cursor first. Deselecting the takeoff on the same page
  still releases it.
- **Deleted Bids cannot be deleted from outside the menus.** The database layer
  now refuses to delete the system project "Deleted Bids" (Access and SQL Server);
  before, only the project tree and its menu blocked it.
- **A bid with an unreadable status is treated as locked.** If a bid's job status
  could not be read or found, the bid used to read as unlocked and could be edited.
  It now reads as locked on Access and on SQL Server.
- **AI regions no longer depend on the order the lines were drawn in.** The same
  drawing now gives the same regions whichever order its lines are read in, and a
  wall drawn twice no longer makes a room disappear or leaves a sliver region.
- **A minus before an elevation applies to the whole value.** `@T - 5' 6"` is
  -5' 6" (it was read as +5' 6"), `@T -1m 20cm` is -120 cm (it was -80 cm), and
  `@T - 1 m` is read instead of being skipped. Converting `1 cm` to metric keeps
  `1 cm` instead of `1.00 cm`.
- **OSP packages with unsafe file names are refused.** An OSP package that contains a file named after a
  Windows reserved device (NUL, CON, AUX, COM1, LPT1 and the like, with or without an extension) or a file
  or folder name ending in a dot or a space is now rejected as unsafe instead of being extracted, and any
  member that would be extracted outside its temporary folder is refused.
- **Compact/Repair keeps your database if the app is interrupted.** Compact/Repair no longer risks deleting
  the only copy of your database if the application is interrupted while the compacted file is being
  swapped in, including a second interrupt during recovery.
- **Interrupting a save no longer lets a half-written change be saved.** Pressing Ctrl+C during a database
  save no longer leaves the half-written change pending for the next save to commit.
- **The MCP server survives damaged state files.** It now starts and reloads cleanly even when its saved
  state files are damaged in unusual ways (extremely nested JSON, oversized numbers or an unexpected
  workspace layout), and it ignores a saved database path that is too long for Windows instead of failing
  to start.
