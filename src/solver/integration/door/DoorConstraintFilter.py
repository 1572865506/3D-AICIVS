from .ReservedRegionManager import ReservedRegionManager


class DoorConstraintFilter:
    """Pre-validation filter applied by the integration envelope before core validation."""

    def __init__(self, context):
        self.context = context
        self.regions = ReservedRegionManager(context.blocked_area)

    def evaluate(self, placement, role="MAIN_CARGO"):
        if role == "DOOR_WALL":
            expected = self.context.forced_orientation.get(placement.sku_id)
            if expected != "SHORT_EDGE_FORWARD":
                return False, "DOOR_ORIENTATION_FORBIDDEN"
        result = self.regions.validate(placement, role)
        return result.valid, result.reason or None
