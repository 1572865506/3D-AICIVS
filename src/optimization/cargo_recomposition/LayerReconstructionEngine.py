class LayerReconstructionEngine:
    def analyze(self,placements):
        heights=sorted({round(p.min_z,3) for p in placements if not p.placement_id.startswith("door_pre_")})
        gaps=[b-a for a,b in zip(heights,heights[1:])]
        balance=max(0.0,100.0-10.0*(sum(gaps)/max(len(gaps),1)))
        return {"layer_count":len(heights),"balance":round(balance,4),"complete_support_required":True}
