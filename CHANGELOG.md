# Changelog

## Unreleased

### Fixed

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
