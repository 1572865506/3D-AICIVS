from collections import defaultdict
from .types import CargoGroup

class CargoGroupingEngine:
    PRIORITY={"HEAVY":0,"STANDARD":1,"DISPLAY":2,"FRAGILE":3}
    def group(self,pool):
        grouped=defaultdict(list)
        for item in pool.items:
            category="DISPLAY_WALL" if item["category"]=="DISPLAY" else "HEAVY_BASE" if item["category"]=="HEAVY" else "FRAGILE" if item["fragility"]=="HIGH" else "MAIN_WALL"
            grouped[category].append(item["id"])
        return tuple(CargoGroup(f"GROUP_{name}",name,tuple(ids),self.PRIORITY.get(name.replace("_WALL",""),1)) for name,ids in sorted(grouped.items()))
