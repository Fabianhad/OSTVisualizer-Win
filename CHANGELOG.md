# Changelog

## Unreleased

### Fixed

- **No monitor warning in the log.** When Windows cannot read a monitor's
  identity data (typically a virtual, disconnected or docked display, or a
  remote desktop session), the log no longer shows the harmless warning
  "Unable to open monitor interface to `\\.\DISPLAY2`: Unknown error
  0xe0000225." It is recorded once per display at debug level instead.
  Other display warnings are still logged.
