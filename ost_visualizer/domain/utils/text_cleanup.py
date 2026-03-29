import re

_XML_NEWLINE_ENTITIES = re.compile(r"&#xa;|&#x0A;|&#10;|&#xA;", re.IGNORECASE)


def strip_xml_newline_entities(text: str) -> str:
    return _XML_NEWLINE_ENTITIES.sub("", text)
