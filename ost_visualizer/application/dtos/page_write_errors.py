PAGE_DELETE_WOULD_LEAVE_NO_PAGE = "page_delete_would_leave_no_page"


class PageScaleRangeError(ValueError):
    """A scale change would store a non-finite position or round one to 0."""
