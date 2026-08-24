class DoorDirectionPolicy:
    risky_categories = {"DISPLAY", "GLASS", "FRAGILE"}

    def evaluate(self, profile, facing, context="MAIN_WALL"):
        constrained = profile.category.value in self.risky_categories or profile.fragility == "HIGH"
        if context=="DOOR_OPEN_BLOCKING_WALL" and constrained and facing != "LONG_EDGE_FORWARD":
            return False, "DOOR_OPEN_BASE_DEPTH_INSUFFICIENT"
        if context!="DOOR_OPEN_BLOCKING_WALL" and constrained and facing == "LONG_EDGE_FORWARD":
            return False, "MAIN_DISPLAY_LONG_EDGE_FORWARD_FORBIDDEN"
        return True, None
