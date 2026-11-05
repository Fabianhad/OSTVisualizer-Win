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
