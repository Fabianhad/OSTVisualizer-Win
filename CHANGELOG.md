# Changelog

## Unreleased

### Added

- **Edges option.** Options > Options has a new **Edges** checkbox that draws
  object outlines and creases in the 3D view, without triangle diagonals. It is
  saved with the other preferences and is the starting state of the Edges
  toggle in HTML exports.
- **Section cuts in 3D.** The 3D view (embedded and detached) and HTML exports
  have **Cut north–south** and **Cut east–west** sliders that cut the model
  with a plane across either plan axis. The slider shows the cut's distance from
  the model's edge in feet, and the right end turns it off. Cut faces are filled,
  slightly darker than the element, also on transparent objects and with Edges
  on, and clicking in the 3D view ignores anything on the removed side.
- **Tower cranes in 3D.** Count takeoffs whose condition notes contain
  "(CRANE)" show a tower crane standing on the takeoff in the 3D view and in
  HTML exports, turned with the takeoff. The takeoff itself is the crane
  footing and keeps its size and quantities; the crane is for show only and
  follows the layer, condition and area filters, section cuts and Edges. A
  **Tower crane** checkbox next to the cut sliders (and in the export's View
  controls) hides the cranes. Crane model: "Tower Crane" by Chamod on
  Sketchfab, CC BY 4.0, credited in Help > About.

### Changed

- **Redesigned HTML export.** The exported page has a header with the bid name
  and bid notes, a model viewport with the Plan/3D switch, page list, Reset view
  and theme buttons, and a side column with visibility and view controls, in
  light and dark themes.
- **HTML export colours match the 3D view.** The export uses the same lighting
  and transparency as the app's 3D view instead of darker, tone-mapped shading.
- **Show by in the HTML export.** The Visibility panel shows Layers, Conditions
  or Areas through a Show by list, with Show all and Hide all for the shown
  group. Each group keeps its checkboxes when you switch, and an object shows
  only when its layer, condition and area are all on.
- **3D view starts the right way round.** Fit and reset in the 3D view now look
  at the model from the same side and height as the HTML export, so the plan is
  no longer shown upside down.