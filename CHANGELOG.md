# Changelog

## 1.2.4.2 - Unreleased

### Fixed

- Export actions now clear stale bid context and disable bid-scoped exports when selecting a database or other non-bid project tree node.
- HTML exports from multi-page PDFs now embed only the selected source PDF pages instead of the full original PDF or an earlier page from the same file.
- Annotation View now ignores duplicate open requests while the first detached window is still being created.
- Conditions sidebar refreshes no longer reapply stale scroll positions from a previous project or rebuild.
- Changing the active Area now immediately refreshes current-page takeoff overlay styling without requiring a page switch.
- Switching pages after entering rotate mode from placement no longer raises an unhandled placement cursor assertion.
- Re-enabling the Image layer now reloads the current page image when the visual layer was hidden across project switches or app restarts.
- Takeoff edit previews now keep inactive-area styling instead of temporarily showing grayed-out items in full condition color.
- PDF page rendering now retains a useful working set of large plan sheets instead of evicting most cached pages after only a few renders.
- Tree views now use the same indentation as the Conditions sidebar throughout the app.
- Summary CSV exports now place area labels before condition type, expand multi-area details with trailing totals, and match expected whole-number quantity formatting.
- New area takeoffs now keep the OST curve flag disabled so polygon and rectangle areas recalculate correctly in OST.
