from .types import RebuildStrategy


class LayoutCandidateGenerator:
    def generate(self):
        return (
            RebuildStrategy("candidate_01","INCUMBENT","accepted BLK007F5 wall order"),
            RebuildStrategy("candidate_02","DISPLAY_FIRST","co-locate display wall slabs"),
            RebuildStrategy("candidate_03","HEAVY_FIRST","heavy base wall slabs first"),
            RebuildStrategy("candidate_04","LAYER_BALANCED","smooth adjacent wall heights"),
            RebuildStrategy("candidate_05","DOOR_SAFE","fragile/display walls nearest transition"),
        )
