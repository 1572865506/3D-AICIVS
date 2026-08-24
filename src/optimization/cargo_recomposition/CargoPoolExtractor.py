import re
from .types import CargoPool
from src.cargo.dimension_normalization import DimensionNormalizer

class CargoPoolExtractor:
    @staticmethod
    def wall_id(placement):
        match=re.search(r"(transition_wall_|cargo_wall_|top_cargo_wall_|top_region_)(\d{3})",placement.placement_id,re.I)
        return (("TRANSITION_WALL_" if match and match.group(1).lower().startswith("transition") else "CARGO_WALL_")+match.group(2)) if match else "LOCKED_OR_RESIDUAL"
    def __init__(self):self.normalizer=DimensionNormalizer()
    def extract(self,placements,intelligence,cargo=None):
        catalog={s.sku_id:s for s in (cargo or ())}
        items=[]
        for p in placements:
            profile=intelligence.profiles[p.sku_id]
            dimension=self.normalizer.normalize_sku(catalog[p.sku_id],profile.category.value=="DISPLAY") if p.sku_id in catalog else None
            items.append({"id":p.placement_id,"sku":p.sku_id,**(dimension.to_dict() if dimension else {}),
                "occupiedDimensions":{"x":p.orientation.dx,"y":p.orientation.dy,"z":p.orientation.dz,"axisDefinition":{"x":"CONTAINER_X","y":"CONTAINER_Y","z":"CONTAINER_Z"}},"weight":p.weight_kg,
                "fragility":profile.fragility,"category":profile.category.value,"preferred_orientation":p.orientation.name,
                "original_wall":self.wall_id(p),"original_position":[p.position.x,p.position.y,p.position.z]})
        return CargoPool(tuple(items),len({x["original_wall"] for x in items if x["original_wall"]!="LOCKED_OR_RESIDUAL"}))
