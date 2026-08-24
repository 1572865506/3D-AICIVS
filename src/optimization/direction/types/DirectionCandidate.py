from dataclasses import dataclass


@dataclass(frozen=True)
class DirectionCandidate:
    sku: str
    orientation: str
    facing: str
    forward_depth: float
    wall_width: float
    reason: str
    risk: object
    score: object

    def to_dict(self):
        return {
            "sku": self.sku, "orientation": self.orientation, "facing": self.facing,
            "forward_depth": self.forward_depth, "wall_width": self.wall_width,
            "reason": self.reason, "risk": self.risk.to_dict(), "score": self.score.to_dict(),
        }
