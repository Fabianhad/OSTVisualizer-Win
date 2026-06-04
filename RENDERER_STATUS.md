# Renderer Status Note

The high-resolution PDF renderer is currently considered broken pending manual verification.

Recent work replaced the tile grid with a visible-region renderer and fixed a native frame orientation issue, but user testing still reported high-zoom rendering problems. Treat this rendering path as unstable until Original, Overlay, and Both modes are manually verified at the problematic zoom levels.

Manual checks should include at least 99%, 113%, 130%, and 229% zoom with PDF base pages and PDF overlays.
