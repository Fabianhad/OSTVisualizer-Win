from ....application.interfaces.i_coordinate_transformer import ICoordinateTransformer
from ....application.interfaces.i_coordinate_transformer_factory import (
    ICoordinateTransformerFactory,
)
from ....domain.services.coordinate_transformation_service import OSTCoordinateSystem


class CoordinateTransformerFactory(ICoordinateTransformerFactory):
    def create(self) -> ICoordinateTransformer:
        return OSTCoordinateSystem()
