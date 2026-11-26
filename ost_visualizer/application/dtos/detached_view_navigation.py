from enum import Enum


class DetachedViewNavigationSource(str, Enum):
    HOTLINK = "hotlink"
    PAGE_COMBO = "combobox"
    NAMED_VIEW_COMBO = "named_view_combo"
    WINDOW_TOGGLE = "window_toggle"
    RESTORE = "restore"
    REFRESH = "refresh"


USER_NAVIGATION_SOURCES = frozenset(
    {
        DetachedViewNavigationSource.HOTLINK,
        DetachedViewNavigationSource.PAGE_COMBO,
        DetachedViewNavigationSource.NAMED_VIEW_COMBO,
        DetachedViewNavigationSource.WINDOW_TOGGLE,
    }
)
NAMED_VIEW_FOCUS_SOURCES = frozenset(
    {
        DetachedViewNavigationSource.HOTLINK,
        DetachedViewNavigationSource.NAMED_VIEW_COMBO,
        DetachedViewNavigationSource.WINDOW_TOGGLE,
        DetachedViewNavigationSource.RESTORE,
    }
)
