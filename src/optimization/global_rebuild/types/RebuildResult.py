from dataclasses import dataclass


@dataclass(frozen=True)
class RebuildResult:
    status: str
    mode: str
    incumbent: object
    candidates: tuple
    best_layout: object
    comparison: dict
    reason: str

    def to_dict(self):
        return {"status":self.status,"mode":self.mode,"incumbent":self.incumbent.to_dict(),
                "candidates":[x.to_dict() for x in self.candidates],"best_layout":self.best_layout.to_dict(),
                "comparison":self.comparison,"reason":self.reason}
