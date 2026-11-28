from typing import Iterable, Mapping, Optional, Tuple
from ..entities.annotation import ANNOTATION_TYPE_CALLOUT, ANNOTATION_TYPE_TEXT

ANNOTATION_TEXT_ENCODING = "latin-1"
_STORED_TEXT_TYPES = frozenset({ANNOTATION_TYPE_TEXT, ANNOTATION_TYPE_CALLOUT})


def first_unstorable_annotation_character(text: object) -> Optional[str]:
    for character in str(text or ""):
        try:
            character.encode(ANNOTATION_TEXT_ENCODING)
        except UnicodeEncodeError:
            return character
    return None


def first_unstorable_character_in_annotations(
    items: Iterable[Tuple[str, Mapping[str, object]]],
) -> Optional[str]:
    for annotation_type, properties in items:
        if annotation_type not in _STORED_TEXT_TYPES:
            continue
        character = first_unstorable_annotation_character(properties.get("Text"))
        if character is not None:
            return character
    return None
