class CargoSequencePlanner:
    ORDER=("HEAVY_BASE","MAIN_WALL","DISPLAY_WALL","FRAGILE","TOP_FILL")
    def plan(self,groups): return tuple(sorted(groups,key=lambda g:(self.ORDER.index(g.category) if g.category in self.ORDER else 99,g.group_id)))
