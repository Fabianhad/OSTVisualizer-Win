from ...domain.entities.named_view import NamedView

NAMED_VIEW_FOCUS_MARGIN = 0.1


def focus_plan_view_on_named_view(plan_view, named_view: NamedView) -> None:
    plan_view.zoom_to_rect(
        named_view.min_x,
        named_view.min_y,
        named_view.max_x,
        named_view.max_y,
        margin=NAMED_VIEW_FOCUS_MARGIN,
    )
