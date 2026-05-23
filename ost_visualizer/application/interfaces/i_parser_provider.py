from typing import Dict, Protocol
from ...domain.repositories.i_file_parser import IFileParser


class IParserProvider(Protocol):
    def get_parsers(self) -> Dict[str, IFileParser]: ...
