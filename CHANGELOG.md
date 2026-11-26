# Changelog

## Unreleased

### Changed

- **Consistent wording.** Dialog titles, buttons, menus, tooltips, labels and
  messages now follow one style: Title Case for titles, buttons and menu items;
  sentence case for tooltips, check boxes and messages; US spelling; "hotlink"
  as one word (the Hotlink History window and the Options hotlink setting);
  errors that start with "Failed to"; quoted names in double quotes; and a
  space before px in line widths. Messages that count pages or items now read
  "1 page" or "2 pages" instead of "page(s)".

### Fixed

- **Paste guides line up with the originals.** After a paste, dragging the
  pasted objects back toward the copied ones shows the horizontal and vertical
  dashed guides together again when the copy sits on the originals. Before,
  often only one pair showed (or none), depending on the order the objects
  were copied in, on areas with backouts or attachments, and on ink
  annotations. On pages rotated 90 or 270 degrees, the pasted objects now snap
  along the axis whose guide is shown instead of jumping along the other one.
  Pastes on SQL Server bids now show the guides too, as Access bids do.
- **Delete from the right-click menu deletes everything selected.** After
  Select All (or any multiple selection), right-clicking on the outline or a
  corner of a selected area or polygon annotation no longer reduces the
  selection to that one object, so Delete removes all the selected objects.
  Right-clicking the outline of an object that is not selected still selects
  only that object.
- **The Conditions sidebar scrolls only when it has to.** Next and Previous in
  Edit Condition no longer scroll the list when the condition's row is already
  visible, even when the sidebar is narrower than its columns. After you update
  a condition that was out of view, the list scrolls so that the whole row is
  visible, instead of leaving it half hidden behind the horizontal scroll bar.
- **The app always closes after an SQL Server cleanup problem.** When the
  SQL collaboration session could not be closed (for example a Windows
  account that only reads the database, or a connection that already
  dropped), closing showed "Shutdown Incomplete" and the app could only be
  ended from Task Manager. It now shows the problem once and closes; SQL
  Server releases that session and its edit locks within about a minute.
- **Reload ends a stuck SQL recovery.** When the automatic recovery after an
  SQL synchronization problem failed (for example while another computer kept
  changing the same bid), the status could stay on recovery or refresh
  required until the app was restarted, because Reload did not try again.
  Reload now starts a new recovery.