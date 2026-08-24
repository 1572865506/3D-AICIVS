from dataclasses import dataclass

@dataclass(frozen=True)
class CargoGroup:
    group_id: str
    category: str
    members: tuple
    priority: int
    def to_dict(self): return {"group_id":self.group_id,"category":self.category,"members":list(self.members),"priority":self.priority}
