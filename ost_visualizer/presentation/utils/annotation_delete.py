from typing import Iterable, List

NAMED_VIEW_HOTLINK_DELETE_MESSAGE = (
    "This named view has hotlinks connected to it.\n"
    "Do you want to delete it and the associated hotlinks?"
)


def order_annotations_for_delete(annotations: Iterable) -> List:
    def rank(annotation) -> int:
        if annotation.is_hotlink:
            return 0
        if annotation.is_namedview:
            return 2
        return 1

    return sorted(list(annotations), key=rank)
