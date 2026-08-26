import re
from collections import defaultdict

from .types import WallProblemRegion


class WallProblemDetector:
    """Detect structural wall defects from geometry, never benchmark x ranges."""
    _WALL = re.compile(r"(cargo_wall|transition_wall)_(\d{3})", re.I)

    @classmethod
    def wall_id(cls, placement):
        match = cls._WALL.search(placement.placement_id)
        return match.group(0).upper() if match else None

    @staticmethod
    def _wall_stats(wall_id, placements, container_width):
        min_x=min(p.min_x for p in placements);max_x=max(p.max_x for p in placements)
        min_y=min(p.min_y for p in placements);max_y=max(p.max_y for p in placements)
        by_column=defaultdict(list);by_layer=defaultdict(list)
        for p in placements:
            by_column[(round(p.min_y,5),round(p.orientation.dy,5))].append(p)
            by_layer[round(p.min_z,5)].append(p)
        incomplete=sum(1 for layer in by_layer.values()
                       if sum(p.orientation.dy for p in layer)<container_width*.90)
        isolated=sum(1 for column in by_column.values() if len(column)==1)
        return {"id":wall_id,"placements":tuple(placements),"min_x":min_x,"max_x":max_x,
                "min_y":min_y,"max_y":max_y,"left":min_y,
                "right":max(0.0,container_width-max_y),"incomplete":incomplete,"isolated":isolated}

    def detect(self, container, placements):
        groups=defaultdict(list)
        for placement in placements:
            wall_id=self.wall_id(placement)
            if wall_id and placement.context.value!="TOP_FILL":groups[wall_id].append(placement)
        walls=sorted((self._wall_stats(wid,ps,container.Ly) for wid,ps in groups.items()),key=lambda w:w["min_x"])
        regions=[]
        for index,wall in enumerate(walls):
            adjacent=walls[index+1] if index+1<len(walls) else None
            gap=max(0.0,adjacent["min_x"]-wall["max_x"]) if adjacent else 0.0
            types=[]
            if gap>.005:types.append("INTER_WALL_GAP")
            if wall["left"]>.01 or wall["right"]>.01:types.append("SIDE_EDGE_GAP")
            if wall["left"]>.01 and wall["right"]>.01:types.append("CENTERED_WALL")
            if wall["isolated"]:types.append("ISOLATED_COLUMN")
            if wall["incomplete"]:types.append("INCOMPLETE_LAYER")
            if not types:continue
            chosen=(wall,adjacent) if adjacent and (gap>.005 or wall["isolated"] or wall["incomplete"]) else (wall,)
            regions.append(WallProblemRegion(
                f"WALL_PROBLEM_{len(regions)+1:03d}",tuple(x["id"] for x in chosen),
                (round(min(x["min_x"] for x in chosen),6),round(max(x["max_x"] for x in chosen),6)),
                tuple(types),round(gap,6),round(wall["left"],6),round(wall["right"],6),
                wall["incomplete"],wall["isolated"]))
        # Overlapping pairs describe the same joint region. Keep deterministic,
        # non-overlapping windows so one placement is never rebuilt twice.
        selected=[];used=set()
        for region in sorted(regions,key=lambda r:(-len(r.problem_types),r.x_range,r.region_id)):
            if used.intersection(region.wall_ids):continue
            selected.append(region);used.update(region.wall_ids)
        return tuple(sorted(selected,key=lambda r:r.x_range))
