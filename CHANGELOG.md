# Changelog

## Unreleased

### Changed

- **Error messages name the cause.** Opening a database, opening a bid,
  Compact/Repair, unloading, saving layers, areas, condition types and
  conditions, connecting to SQL Server, the SQL import and the license
  activation, deactivation and check no longer show raw system or driver
  text such as "[WinError 2] ..." or "Operation failed: ...". When the cause
  is known the message says it in one sentence ("The file is open in another
  program. Close it there and try again.", "Access to the file was denied.",
  "The network location is not available.", "There is not enough space on
  the disk."); otherwise it says that an unexpected error stopped the action
  and what to try. Exports name the cause the same way ("The file could not
  be written. The destination folder was not found. Choose another folder and
  try again."), and a PDF export of a page whose drawing file is missing says
  so for that page. OBJ, DXF, HTML and Summary CSV failures no longer start
  with "Failed to create ... export:", and OSP and PDF write failures use the
  same sentence as the other exports. The local and SQL Server imports use
  the same sentence for a damaged file ("The OSP file is damaged or uses an
  unsupported format, so it cannot be imported."). Messages no longer ask
  people to check the log. The AI takeoff data prompt names the reason when
  it cannot rebind ("The AI takeoff data for this bid is damaged, so nothing
  was rebound."). Progress dialogs read "Exporting: Writing OST...",
  "Importing: job.ost...", "Database setup: Creating schema tables..." and
  "Duplicating: Writing bid data..." instead of splicing the step into a
  sentence, and the cover sheet save error no longer appends the raw
  exception.
- **Error and progress wording.** Export and import failures no longer show
  programmer text such as "Export function returned False.", raw exception
  messages, native PDF writer errors, "Failed to create CAB archive." or
  database table diagnostics. They now say what failed and what to do, for
  example "No file was written. Check that the selected pages have takeoffs
  this format can export, then try again or choose a different destination.",
  "The file could not be written. Please ensure you have write permissions to
  the destination folder and try again." or "The OSP package is damaged or
  uses an unsupported format, so it cannot be imported."; the log keeps the
  details. License messages read as one sentence ("License activated
  successfully. It is valid until 2027-01-31." and "The license is valid until
  2027-01-31." instead of "License activated successfully. until ...").
  Network path errors end with a period and no longer insert "the file
  location" into the sentence. Tower crane notes say "is less than 3 ft"
  instead of "is outside 3 ft or more", and a single section is "1 section".
  AI changeset refusals name the state in words ("The changeset is waiting for
  approval and cannot do that." instead of "pending_approval"). Conflict and
  edit-lock messages no longer show internal resource names ("This item is
  being edited by Alice."). Messages about reloading the database say
  "reload" instead of "refresh". The new Access database progress dialog
  reads "Database setup" with steps such as "Creating schema tables", like
  the SQL Server one, and the duplicate and paste steps start with a capital
  ("Bid 2 of 5"). Missing cover sheet images read "The image file was not
  found:".
- **Wording round.** Messages that are full sentences now end with a period,
  also when they are passed on as an error: "The active bid is locked.",
  "Another license operation is in progress.", "Failed to load file.",
  "Failed to unload file.", "Failed to reload database.", "No file path
  provided.", "The condition update could not be completed.", "Database
  reload failed after saving condition.", "Failed to generate .ost file." and
  "Failed to create CAB archive.". Slabs proposed by the AI are named with a
  space before the unit ("Slab 8 in" instead of "Slab 8in"), and an AI
  assumption says "neighboring" instead of "neighbouring". The Drop/Run box in
  Edit Condition has a tooltip that explains what it adds in the 3D view.
- **Consistent wording.** Dialog titles, buttons, menus, tooltips, labels and
  messages now follow one style: Title Case for titles, buttons and menu items;
  sentence case for tooltips, check boxes and messages; US spelling; "hotlink"
  as one word (the Hotlink History window and the Options hotlink setting);
  errors that start with "Failed to"; quoted names in double quotes; and a
  space before px in line widths. Messages that count pages, items, bids or
  takeoffs now read "1 page" or "2 pages" instead of "page(s)". Field labels
  in the cover sheet and employee dialogs use sentence case. Messages say
  "Reload" when the database or bid has to be reloaded (the SQL status now
  reads "SQL: RELOAD REQUIRED"), the condition delete warning says "This
  cannot be undone." instead of shouting it, and a new condition folder that
  cannot be shown gets its own message. "Select Overlay Image..." reads the
  same in every menu, and the buttons of exported HTML 3D views use Title
  Case. Sentences that read wrongly are fixed: the AI review hint ("Enter a
  valid number."), the export note about condition names that became
  identical after dropping elevations, and the generic "The operation could
  not be completed." fallback. Error and status messages from the license,
  database and SQL Server code follow the same style: they end with a period,
  say "Failed to" instead of "Unable to", use lowercase bid, page, takeoff,
  condition and layer in running text, US spelling ("initialized"), double
  quotes around a database name or character, and "Reload the bid" instead
  of "Refresh the Bid".

### Fixed

- **Conditions.** A new metric Count or Attachment condition is created with
  the 300 mm width the form shows (it was created 12 in wide). A stored
  quantity that the condition's style does not list now shows as a disabled
  "Unknown (N)" entry, so choosing "(none)" clears it; a notes-only edit still
  keeps it. The condition delete question reads "Deleting this condition will
  delete all its takeoffs on all pages within this bid." for one condition
  and starts with "You are deleting N conditions." when several are deleted.
- **Pages and layers.** The last real page of a bid can no longer be deleted
  when the bid also has items without a page. Showing or hiding a single
  locked template layer that other bids share is refused with "This layer is
  a locked template layer that other bids share, so it cannot be shown or
  hidden from this bid." instead of changing the other bids. On SQL Server, a
  layer that a condition uses counts as in use even when the condition has
  no takeoffs, as it already did in Access files, so deleting it no longer
  silently removes the layer from that condition.
- **Paste with snap on.** A pasted group dropped on the alignment guides now
  lands exactly on the aligned position; it used to move off by up to half a
  snap increment.
- **Undo and redo of changes whose page or item is gone.** Undo no longer
  restores items onto a deleted page at the wrong scale. It says "The change
  could not be undone because the page or item it belongs to no longer
  exists. It is still in the undo history." (or the redo sentence) and keeps
  the entry.
- **3D export winding.** Every 3D shape now faces outward in the 3D view, the
  HTML export, OBJ and FBX. Triangle and rhombus count shapes used to be
  inside out in OBJ and FBX files. In the 3D view and the HTML export, the
  side faces of walls, slabs, boxes and cylinders are now lit from the side
  that faces the light.
- **Annotation text the database cannot store.** Text and callout
  annotations with a character that the Access file cannot hold (for example
  the euro sign) are refused with "The annotation text was not saved because
  this database cannot store the character "€" (U+20AC). Remove or
  replace that character, then try again." instead of being dropped
  silently or reported as a page and layer problem.
- **Editing a condition keeps what you did not change.** Saving a condition
  no longer resets a stored quantity that its style does not list (for
  example a Count condition with an area quantity), and a notes-only edit no
  longer rewrites a negative rise or run. The "Unknown (N)" style entry goes
  away once a real style is saved.
- **Elevation text.** The elevation field refuses text after the foot mark
  even when the text contains a quote (`5'x"`, `10'6.3"`) or a letter or digit
  of any script, accepts the typographic inch marks ″ and ” like `"`, and
  refuses a huge number with the normal message instead of failing. A bid
  whose stored condition name holds such a number now loads.
- **New Condition.** The form shows the next condition number instead of 0,
  starts from metric values in a metric bid, uses the bid's own Default layer
  (it used to fail on every save when that layer had been renamed), and closes
  without asking when nothing was changed. A condition with an empty name or
  an invalid number is refused.
- **Renumber and Duplicate say what happened.** Renumber explains why it could
  not renumber, and says so when the numbers were saved but the list could not
  be refreshed. A failed Duplicate now shows a message.
- **Conditions without a type** show "(unassigned)" in the summary row and the
  CSV export, as in their group.
- **Condition folders.** On an Access bid, creating, renaming or deleting a
  condition folder that fails now shows a message, and a rename or delete that
  was saved but whose list could not be refreshed says so instead of looking
  failed. Deleting a folder is refused when a sub-folder holds a condition,
  also when another user added it after you opened the bid. New folders get a
  free name ("New Folder (2)" and so on) instead of a second "New Folder".
- **Layer deletes never drop a layer that is in use.** When the app cannot
  check which layers are in use, a delete is refused with a message instead of
  clearing the layer from its conditions, and the Layers sidebar uses the same
  in-use check as the Layers dialog. A new or renamed layer called "Comments"
  is refused as a duplicate (it used to disappear). A rename, move or delete
  that was saved but whose list could not be refreshed says so. Show All and
  Hide All in a bid with no layers of its own say so in the sidebar too, the
  view after Hide All or Show All matches a reload, and moving a layer next to
  a shared one shows "Failed to move layer." instead of an internal error.
- **Set Scale protects the drawing.** A scale so large or so small that the
  takeoffs and annotations on the page could not be stored is refused with a
  message, and nothing on the page changes (before, every position became
  infinite or zero). "inf" or "nan" as a custom scale is refused as not a
  number. The custom scale fields show the exact stored scale (1234567
  instead of 1.23457e+06), so ticking only "Apply to all pages" no longer
  moves the takeoffs slightly. A legend containing a character such as € no
  longer blocks a scale change.
- **Page names and page deletes.** A page name longer than 255 characters is
  refused when renaming instead of being cut off silently, and when a page is
  deleted but the page list cannot be refreshed the message says the page was
  deleted instead of "Failed to delete page."
- **Rejected takeoffs say so.** On a SQL Server bid, when the database refuses
  takeoffs you just placed (for example because another user is editing the
  bid), a message now says how many were not placed and why, without blocking
  your work, and the removed previews no longer stay selected. When undo or
  redo fails, or when a page or Named View you choose in the detached view
  cannot be shown, a message now explains it instead of nothing happening. A
  locked bid still refuses changes without a message.
- **Opening a detached window explains a failure.** When you open the
  Annotation or View window from its toolbar button, menu item or shortcut
  and its page cannot be shown, a message now explains it. When the app
  reopens these windows at startup, a page that cannot be shown is only
  written to the log, so startup is never interrupted by a message.
- **Clearer AI takeoff messages.** Undoing an AI changeset that cannot be
  undone now says why in plain words for each case, for example "The
  changeset was rejected, so there is nothing to undo." or "The changeset is
  still being applied. Undo it after it finishes.", instead of naming an
  internal status. Slab proposals count holes as "1 hole left out" or "2
  holes left out" instead of "hole(s)".
- **Unexpected failures no longer pass silently.** When the bid areas cannot
  be loaded for the area picker, when saving a page scale fails in the main
  window or in a detached view, or when moving or renaming a layer in an
  Access database fails unexpectedly, a message now explains it instead of
  the change quietly reverting. A locked bid still refuses these changes
  without a message, as before.
- **Every error message is in the log.** Each error, warning and information
  message the app shows is also written to the application log, with the
  technical details and the error's traceback, so a reported problem can be
  traced. Export, import and new-database failures that happened in the
  background worker now keep that worker's traceback, which was missing
  before. Messages are no longer shown while the app is closing.
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