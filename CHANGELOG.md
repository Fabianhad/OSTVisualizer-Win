# Changelog

## Unreleased

### Fixed

- **Cover Sheet and New Project save on SQL Server again.** Saving no longer
  fails with "Object of type datetime is not JSON serializable" because of the
  bid date. If a save still cannot be sent, the dialog shows the error and
  stays open with your changes, and its edit lock is kept until you close it.
- **Drawings on a share you cannot reach no longer crash the app.** When
  Windows rejects the network credentials for a server such as `\\AC-SERVER`,
  or the share, path or permission is unavailable, the page shows as
  unavailable (the bar says the file cannot be accessed and its tooltip gives
  the reason) while takeoffs and quantities keep working; the Cover Sheet opens
  and marks the file as inaccessible; and changes from other SQL Server users
  are still applied. The problem is logged once per file.
- **New Folder works again after a Reload.** When another user's change
  interrupted your condition edit and you chose Reload, New Folder and
  deleting, renaming or moving folders stayed disabled until the app was
  restarted. Reload now clears that state.
- **Compact 3D view controls.** The row with the section cut sliders, Edges
  and Tower crane is again as tall as the toolbar above it, in the 3D view
  and in the 3D window, and the 3D scene uses the rest of the space. Before,
  the row could take half of the 3D view.
- **No monitor warning in the log.** When Windows cannot read a monitor's
  identity data (typically a virtual, disconnected or docked display, or a
  remote desktop session), the log no longer shows the harmless warning
  "Unable to open monitor interface to `\\.\DISPLAY2`: Unknown error
  0xe0000225." It is recorded once per display at debug level instead.
  Other display warnings are still logged.
- **OBJ and DXF exports cut like the 3D view.** A negative takeoff now cuts
  only takeoffs of its own condition type, as in the 3D view and the HTML
  export, instead of every takeoff it touches. A takeoff that negatives remove
  completely is left out instead of coming back whole, and an export with only
  negative takeoffs fails with the same error as the HTML export instead of
  writing an empty file. FBX export follows the same rule.
- **Walls with a drop no longer disappear.** When a wall's drop cannot be
  joined to the wall, the wall is still shown and exported without the drop,
  and the log names the takeoff.
- **Edit Condition keeps metric defaults and your spacing.** Changing a
  condition's type in a metric bid saves the metric defaults the dialog shows
  (for example 150 mm, not 152.4 mm), and a spacing or thickness you typed is
  saved even when it equals the old value.
- **Elevations survive a reload.** Edit Condition only accepts elevations the
  bid can read back, such as `10' 6"` or `3.2 m` / `320 cm`, and says which
  forms work. Before, a metric value such as `3200` was accepted and then
  lost, and `3.2 m` was saved as 3.2 mm.
- **Negative marker on rotated pages.** The red minus marker of a negative
  takeoff stays on its shape when the page is rotated or flipped.
- **Safer OBJ, MTL and DXF text.** Line breaks and other control characters in
  a condition name can no longer add lines to an exported file.
- **Hide All keeps conditions without a layer visible,** as they are after a
  reload.
- **Renumbering a condition without a number** no longer fails.
- **OSP import** no longer stops when a folder has the same name as an image it
  copies, and a date outside the supported range is imported as empty instead
  of stopping the whole import.
- **Snapping stays off when a bid's increment is 0.** A takeoff increment of 0
  saved in the bid is no longer loaded as 1, so snapping stays off as set.
- **Hide All no longer changes other bids.** Hide All and Show All change only
  the open bid's own layers; shared default layers keep their state, as they
  do after a reload.
- **Shading no longer flips when a negative is added.** A 3D shape that no
  negative takeoff cuts keeps the same face orientation, so its lighting in
  the 3D view and HTML export, and its OBJ faces, stay the same when a
  negative takeoff exists elsewhere.
- **Condition numbers above 2147483647** are refused in Edit Condition with a
  clear message, and a renumber that would push another condition past that
  limit fails with a message instead of a generic error, changing nothing.
