class CargoSequencePlanner:
    rank={"DOOR_SAFETY":0,"HEAVY":1,"MAIN_WALL":2,"FRAGILE":3,"TOP_FILL":4}
    def plan(self,cargo,intelligence):
        def group(sku):
            profile=intelligence.profiles[sku.sku_id]
            if profile.loadingPriority.door_priority>=8:return "DOOR_SAFETY"
            if profile.category.value=="HEAVY":return "HEAVY"
            if profile.fragility=="HIGH":return "FRAGILE"
            return "MAIN_WALL"
        return tuple(s.sku_id for s in sorted(cargo,key=lambda s:(self.rank[group(s)],s.sku_id)))
