from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.uom_service_impl import UOMDomainService


class _RecordingUomService(UOMDomainService):
    def __init__(self):
        self.quantity_calls = []

    def calculate_condition_quantities(self, *args, **kwargs):
        self.quantity_calls.append((args, kwargs))
        return super().calculate_condition_quantities(*args, **kwargs)


def _area_fixture(thickness=12.0):
    condition = Condition(
        uid="c1",
        name="Concrete",
        condition_type=Condition.TYPE_AREA,
        thickness=thickness,
        ref_no=7,
    )
    takeoff = Takeoff(
        uid="t1",
        condition_uid="c1",
        position=[0.0, 0.0, 144.0, 0.0, 144.0, 144.0, 0.0, 144.0],
    )
    return condition, takeoff
