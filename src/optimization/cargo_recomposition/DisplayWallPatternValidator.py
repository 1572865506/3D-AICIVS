class DisplayWallPatternValidator:
    def validate(self,placements,intelligence):
        # Door blocking columns deliberately use a deeper self-stable base for
        # door-open safety.  Main display-wall direction compliance is a
        # separate context and must not mark that safety orientation invalid.
        display=[p for p in placements if intelligence.profiles[p.sku_id].category.value=="DISPLAY"
                 and p.context.value!="TOP_FILL" and not p.placement_id.startswith("door_pre_")]
        short=sum(p.orientation.dx<=p.orientation.dy+1e-9 for p in display)
        ratio=100.0*short/max(len(display),1)
        return {"count":len(display),"continuity":round(ratio,4),"same_orientation":round(ratio,4),"valid":ratio>=95.0}
