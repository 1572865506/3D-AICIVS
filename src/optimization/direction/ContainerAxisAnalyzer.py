from .types import AxisStrategy


class ContainerAxisAnalyzer:
    def analyze(self, container):
        # Business loading view is door -> rear; canonical Solver V2 coordinates remain rear -> door.
        return AxisStrategy("X", "-X", "+X", "+Z", "rear_to_door(+X)", "door_to_rear(-X)")
