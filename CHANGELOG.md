# Changelog

## 1.2.4.2 - Unreleased

### Fixed

- Export actions now clear stale bid context and disable bid-scoped exports when selecting a database or other non-bid project tree node.
- HTML exports from multi-page PDFs now embed only the selected source PDF pages instead of the full original PDF or an earlier page from the same file.
- Annotation View now ignores duplicate open requests while the first detached window is still being created.
- Conditions sidebar refreshes no longer reapply stale scroll positions from a previous project or rebuild.
- Changing the active Area now immediately refreshes current-page takeoff overlay styling without requiring a page switch.
- Switching pages after entering rotate mode from placement no longer raises an unhandled placement cursor assertion.
- Hotlink placement now restores the normal cursor outside the plan canvas after choosing a named view while still allowing continuous hotlink placement.
- Bulk named-view deletion now skips only the named views declined during linked-hotlink confirmation instead of canceling the remaining selected deletes.
- Cover Sheet page scale selectors now include all known scale groups, so pages using civil or metric scales show the matching scale instead of a custom-looking value.
- Re-enabling the Image layer now reloads the current page image when the visual layer was hidden across project switches or app restarts.
- Takeoff edit previews now keep inactive-area styling instead of temporarily showing grayed-out items in full condition color.
- 2D View highlight annotations now mark the paper/background without tinting takeoffs, annotation strokes/text/shapes, image overlays, or selection graphics.
- PDF page rendering now retains a useful working set of large plan sheets instead of evicting most cached pages after only a few renders.
- Tree views now use the same indentation as the Conditions sidebar throughout the app.
- Summary CSV exports now place area labels before condition type, expand multi-area details with trailing totals, and match expected whole-number quantity formatting.
- New area takeoffs now keep the OST curve flag disabled so polygon and rectangle areas recalculate correctly in OST.
- OSP/OST exports now prune stale child rows with missing parent records, reject invalid imports with table/UID details, and keep same-named drawing files distinct inside packages.
