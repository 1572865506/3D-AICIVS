from .types import FacingRule


class CargoFacingPlanner:
    def plan(self, sku, profile, wall_role="MAIN_WALL"):
        structural = profile.category.value in {"DISPLAY", "GLASS"} or profile.fragility == "HIGH"
        preferred = "SHORT_EDGE_FORWARD" if structural else "SHORT_EDGE_FORWARD"
        door = wall_role == "DOOR_WALL"
        forbidden = ("LONG_EDGE_FORWARD",) if door and structural else ()
        reason = "DISPLAY_WALL_STABILITY" if profile.category.value == "DISPLAY" else "TRANSPORT_AND_WALL_CONTINUITY"
        return FacingRule(sku.sku_id, wall_role, preferred,
                          ("SHORT_EDGE_FORWARD", "LONG_EDGE_FORWARD"), forbidden,
                          reason, profile.source, door and structural)
