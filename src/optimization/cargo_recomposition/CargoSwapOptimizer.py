from dataclasses import replace

class CargoSwapOptimizer:
    def lateral_recompose(self,placements,container,enabled):
        if not enabled:return tuple(placements)
        return tuple(p if p.placement_id.startswith("door_pre_") else
            replace(p,position=replace(p.position,y=round(container.Ly-p.position.y-p.orientation.dy,6))) for p in placements)
