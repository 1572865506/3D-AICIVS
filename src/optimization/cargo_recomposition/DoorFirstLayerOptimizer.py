class DoorFirstLayerOptimizer:
    def validate(self,placements):
        door=[p for p in placements if p.placement_id.startswith("door_pre_")]
        columns={}
        for p in door:columns.setdefault(round(p.min_y,6),[]).append(p)
        safe=0
        for items in columns.values():
            depth=max(p.orientation.dx for p in items);height=max(p.max_z for p in items)-min(p.min_z for p in items)
            if min(p.min_z for p in items)<=1e-9 and depth/max(.15*height,1e-9)>=1.0:safe+=1
        ratio=100.0*safe/max(len(columns),1)
        return {"count":len(columns),"door_open_stable_pct":round(ratio,4),
                "door_safety_score":round(ratio,4),"short_edge_forward_pct":0.0,
                "stable":bool(columns) and ratio>=95.0}
