class WallMergeOptimizer:
    """Canonicalizes adjacent equal-composition walls into structural chain segments."""
    def merge(self,walls,transition_walls):
        raw=[]
        for wall in walls:
            sku=next(iter(wall.to_dict()["sku_mix"]),"")
            orientation=wall.placements[0].orientation.name if wall.placements else ""
            raw.append({"source_ids":[wall.id],"sku":sku,"orientation":orientation,"x_range":[wall.x_start,wall.x_end],"role":wall.role})
        for wall in transition_walls:
            raw.append({"source_ids":[wall.id],"sku":wall.source_sku,"orientation":wall.orientation,"x_range":list(wall.x_range),"role":wall.role})
        merged=[]
        for segment in sorted(raw,key=lambda s:s["x_range"][0]):
            if merged and merged[-1]["sku"]==segment["sku"] and merged[-1]["orientation"]==segment["orientation"] and abs(merged[-1]["x_range"][1]-segment["x_range"][0])<=1e-6:
                merged[-1]["source_ids"].extend(segment["source_ids"]);merged[-1]["x_range"][1]=segment["x_range"][1]
            else:merged.append(segment)
        for index,segment in enumerate(merged,1):segment["merged_id"]=f"MERGED_WALL_{index:03d}"
        return tuple(merged)
