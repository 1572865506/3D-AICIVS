from typing import Iterable, Tuple

from .types import WallLayer


class WallLayerBuilder:
    def build(self, placements: Iterable, container_width: float) -> Tuple[WallLayer, ...]:
        placements=tuple(placements);result=[]
        for index,z in enumerate(sorted({round(p.min_z,6) for p in placements})):
            row=sorted((p for p in placements if abs(p.min_z-z)<=1e-6),key=lambda p:p.min_y)
            cursor=0.0;gaps=[]
            for p in row:
                if p.min_y>cursor+1e-9:gaps.append(p.min_y-cursor)
                cursor=max(cursor,p.max_y)
            if cursor<container_width-1e-9:gaps.append(container_width-cursor)
            result.append(WallLayer(index,z,max(p.max_z for p in row),tuple(p.placement_id for p in row),
                round(sum(p.orientation.dy for p in row)/container_width,6),len(gaps),round(max(gaps,default=0.0),6)))
        return tuple(result)
