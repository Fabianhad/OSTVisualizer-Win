# Changelog

## 1.2.4.2 - Unreleased

### Changed

- Plan-view cloud annotations now render with smaller scallops for a less bulky outline.
- Annotation View windows now place annotation tools on a second toolbar row, keeping navigation and view controls on the first row.

### Fixed

- Export actions now clear stale bid context and disable bid-scoped exports when selecting a database or other non-bid project tree node.
- HTML exports from multi-page PDFs now embed only the selected source PDF pages instead of the full original PDF or an earlier page from the same file.
- Annotation View now ignores duplicate open requests while the first detached window is still being created.
- Conditions sidebar refreshes no longer reapply stale scroll positions from a previous project or rebuild.
- Changing the active Area now immediately refreshes current-page takeoff overlay styling without requiring a page switch.
- Switching pages after entering rotate mode from placement no longer raises an unhandled placement cursor assertion.
- Hotlink placement now restores the normal cursor outside the plan canvas after choosing a named view while still allowing continuous hotlink placement.
- Named View creation now commits when switching tools, so selecting the mouse cursor no longer reactivates the Named View tool afterward.
- Bulk named-view deletion now skips only the named views declined during linked-hotlink confirmation instead of canceling the remaining selected deletes.
- Cover Sheet page scale selectors now include all known scale groups, so pages using civil or metric scales show the matching scale instead of a custom-looking value.
- Cover Sheet Plan Organizer columns now keep their header layout between dialog openings.
- Re-enabling the Image layer now reloads the current page image when the visual layer was hidden across project switches or app restarts.
- Takeoff edit previews now keep inactive-area styling instead of temporarily showing grayed-out items in full condition color.
- 2D View highlight annotations now mark the paper/background without tinting takeoffs, annotation strokes/text/shapes, image overlays, or selection graphics.
- PDF page rendering now retains a useful working set of large plan sheets instead of evicting most cached pages after only a few renders.
- Tree views now use the same indentation as the Conditions sidebar throughout the app.
- Summary CSV exports now place area labels before condition type, expand multi-area details with trailing totals, and match expected whole-number quantity formatting.
- New area takeoffs now keep the OST curve flag disabled so polygon and rectangle areas recalculate correctly in OST.
- OSP/OST exports now prune stale child rows with missing parent records, reject invalid imports with table/UID details, and keep same-named drawing files distinct inside packages.
- The Takeoff cursor now remains available on the active 2D page even when that page is unchecked for 3D/multi-page selection.
- Copying plan-view selections now copies only items loaded on the active 2D page, preventing stale off-page takeoffs from being pasted while keeping selected text annotations in the paste set.
- Cover Sheet page scale changes now preserve takeoff placement the same way as the Takeoff tab scale control instead of visually resizing area takeoffs.
- Annotation View windows now recover when their active page is deleted from Cover Sheet instead of recursing during page navigation.
- Bid deletion no longer gets blocked by a stale deferred selected-page write for the bid being removed.
