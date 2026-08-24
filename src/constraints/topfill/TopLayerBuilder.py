from .types import TopLayer
class TopLayerBuilder:
    def build(self,placements):
        import re
        result=[];regions={}
        for p in placements:
            match=re.search(r"TOP_REGION_\d+",p.placement_id);region=match.group(0) if match else "TOP_REGION_UNKNOWN"
            regions.setdefault(region,[]).append(p)
        for region,items in sorted(regions.items()):
            for index,z in enumerate(sorted({round(p.min_z,6) for p in items}),1):
                row=tuple(p for p in items if abs(p.min_z-z)<=1e-6)
                result.append(TopLayer(region,index,z,max((p.orientation.dz for p in row),default=0),tuple(p.placement_id for p in row),1.0))
        return tuple(result)
