from typing import Protocol
from .i_coordinate_transformer import ICoordinateTransformer


class ICoordinateTransformerFactory(Protocol):
    def create(self) -> ICoordinateTransformer: ...
