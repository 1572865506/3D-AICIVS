class WallConstraintFilter:
    """Cheap formation gate; full collision/support validation remains downstream."""
    def evaluate(self,wall):
        if not wall.layers:return False,"EMPTY_WALL"
        if any(layer.gap_count>1 for layer in wall.layers):return False,"DISCONTINUOUS_LAYER"
        if wall.stability.get("isolatedCargo"):return False,"ISOLATED_CARGO"
        if wall.stability.get("weakArea"):return False,"WEAK_SUPPORT_AREA"
        return True,None
