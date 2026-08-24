from .types import DirectionCandidate


class DirectionSimulation:
    def __init__(self, transport, scores, door_policy):
        self.transport = transport
        self.scores = scores
        self.door_policy = door_policy

    def simulate(self, sku, profile, facing, wall_role, dimension):
        short = dimension.width
        long = dimension.length
        forward = short if facing == "SHORT_EDGE_FORWARD" else long
        width = long if facing == "SHORT_EDGE_FORWARD" else short
        orientation = "UPRIGHT_NORMAL" if abs(forward - dimension.length) < 1e-9 else "UPRIGHT_ROTATED"
        risk = self.transport.analyze(sku, facing, dimension)
        door_ok, _ = self.door_policy.evaluate(profile, facing,wall_role)
        space = 100.0 * min(1.0, width / max(long, 1e-12))
        continuity = 100.0 if facing == "SHORT_EDGE_FORWARD" else 65.0
        door = 100.0 if door_ok else 0.0
        layer = 95.0 if orientation.startswith("UPRIGHT") else 75.0
        score = self.scores.score(space, continuity, risk.transport_score, door, layer, 100-risk.transport_score)
        reason = "DISPLAY_WALL_STABILITY" if profile.category.value == "DISPLAY" and facing == "SHORT_EDGE_FORWARD" else "GLOBAL_DIRECTION_SCORE"
        return DirectionCandidate(sku.sku_id, orientation, facing, round(forward, 6), round(width, 6), reason, risk, score)
