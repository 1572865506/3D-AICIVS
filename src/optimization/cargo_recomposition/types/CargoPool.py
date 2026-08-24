from dataclasses import dataclass

@dataclass(frozen=True)
class CargoPool:
    items: tuple
    original_wall_count: int
    def to_dict(self):
        return {"cargo_count":len(self.items),"original_wall_count":self.original_wall_count,"items":list(self.items)}
