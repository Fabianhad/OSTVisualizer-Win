# Changelog

## 1.3.2 - Unreleased

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
- **Tower cranes in 3D.** Count takeoffs whose condition notes contain a
  "[crane]" tag show a tower crane standing on the takeoff in the 3D view and
  in HTML exports, turned with the takeoff. The takeoff itself is the crane
  footing and keeps its size and quantities; the crane is for show only and
  follows the layer, condition and area filters, section cuts and Edges. A
  **Tower crane** checkbox next to the cut sliders (and in the export's View
  controls) hides the cranes. Crane model: "Tower Crane" by Chamod on
  Sketchfab, CC BY 4.0, credited in Help > About.
- **Crane shape from the notes.** The tag takes arguments that shape the
  crane, the same in the 3D view and in HTML exports, for example
  "[crane mast=30 jib=24 counterjib=6 trolley=50% hook=40]". **mast**, **jib**
  and **counterjib** are numbers of sections (25, 18 and 7 when left out); a
  length such as "mast=150ft" is rounded to whole sections. **trolley** is a
  percentage of its travel along the jib (79% when left out) or a distance
  from the mast. **hook** is the rope length below the trolley and
  **hookheight** the hook's height above the footing. A plain number is feet;
  "ft" and "m" also work. The ropes follow the mast, jib, trolley and hook.
  A value the crane cannot use keeps its default, and Edit Condition lists
  such problems before saving, with **Save anyway** and **Go back**.
- **Second crane model.** "[crane model=liebherr]" shows the "Liebherr tower
  crane" by Cem Alagozlu (Sketchfab, CC BY 4.0) instead of the default model
  ("model=classic", used when the tag names none). Both cranes are yellow
  (#edcf0c); the Liebherr has a white cab with the same glass and the same
  concrete counterweight as the default crane. Each model has its own
  sections, defaults and limits (the Liebherr's are 19 mast, 32 jib and 9
  counterjib sections), so a length such as "jib=50m" turns into that model's
  sections. Both models can stand in one bid. HTML exports embed only the
  models they show and credit each one; Help > About credits both.
- **Tower crane and Edges options.** Options has a **Tower crane** checkbox
  below **Edges** (on by default, saved). The 3D view has an **Edges**
  checkbox next to **Tower crane**; both are the same settings as Options, stay
  in sync with it and with the detached 3D window, and set the defaults of the
  HTML export's toggles. **Show text on selected toolbars** moved to the right
  column of the Options tab.

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