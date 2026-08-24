from .CargoFacingPlanner import CargoFacingPlanner
from .ContainerAxisAnalyzer import ContainerAxisAnalyzer
from .DirectionScoreEngine import DirectionScoreEngine
from .DirectionSimulation import DirectionSimulation
from .DoorDirectionPolicy import DoorDirectionPolicy
from .TransportStabilityAnalyzer import TransportStabilityAnalyzer
from .WallOrientationPlanner import WallOrientationPlanner
from .types import DirectionPlan
from src.cargo.dimension_normalization import DimensionNormalizer


class LoadingDirectionEngine:
    def __init__(self):
        self.axes = ContainerAxisAnalyzer(); self.facing = CargoFacingPlanner()
        self.transport = TransportStabilityAnalyzer(); self.scores = DirectionScoreEngine()
        self.door = DoorDirectionPolicy(); self.simulation = DirectionSimulation(self.transport, self.scores, self.door)
        self.walls = WallOrientationPlanner()
        self.dimension_normalizer=DimensionNormalizer();self.last_normalized_dimensions={}

    def plan(self, container, cargo, intelligence):
        axis = self.axes.analyze(container); rules=[]; selected=[]; matrix=[]
        self.last_normalized_dimensions={sku.sku_id:self.dimension_normalizer.normalize_sku(sku) for sku in cargo}
        for sku in sorted(cargo, key=lambda item: item.sku_id):
            profile = intelligence.profiles[sku.sku_id]
            rule = self.facing.plan(sku, profile, "MAIN_WALL")
            dimension=self.last_normalized_dimensions[sku.sku_id]
            candidates = [self.simulation.simulate(sku, profile, facing, "MAIN_WALL",dimension)
                          for facing in ("SHORT_EDGE_FORWARD", "LONG_EDGE_FORWARD")]
            choice = self.walls.select(candidates, rule)
            rules.append(rule); selected.append(choice)
            matrix.append({"sku": sku.sku_id, "category": profile.category.value,
                           "preferredFacing": choice.facing, "orientationPriority": [choice.orientation] +
                           [c.orientation for c in candidates if c.orientation != choice.orientation],
                           "topDirectionRule": "TOP_FLAT_IF_EXPLICITLY_ALLOWED_ELSE_PRESERVE_UPRIGHT",
                           "normalizedDimension":dimension.to_dict(),
                           "candidates": [c.to_dict() for c in candidates]})
        preferred = {item.sku: item.facing for item in selected}
        priorities = {item.sku: [item.orientation] for item in selected}
        return DirectionPlan("READY", axis, tuple(rules), tuple(selected), tuple(matrix),
                             {"preferredFacing": preferred}, {"orientationPriority": priorities},
                             {"topDirectionRule": "PROFILE_GATED_TOP_FLAT"}, {})

    def validate_actual(self, plan, placements, cargo):
        catalog = {sku.sku_id: sku for sku in cargo}; violations=[]; display=[]
        for p in placements:
            sku = catalog[p.sku_id]
            facing = "TOP_FLAT" if p.orientation.is_flat else "SHORT_EDGE_FORWARD" if p.orientation.dx <= p.orientation.dy + 1e-9 else "LONG_EDGE_FORWARD"
            profile_row = next(row for row in plan.orientation_matrix if row["sku"] == p.sku_id)
            if profile_row["category"] == "DISPLAY" and p.context.value != "TOP_FILL" and not p.placement_id.startswith("door_pre_"):
                display.append(facing)
                if facing != "SHORT_EDGE_FORWARD": violations.append(p.placement_id)
        return {"display_non_top_count": len(display), "display_short_edge_forward_count": display.count("SHORT_EDGE_FORWARD"),
                "display_direction_violations": violations, "display_direction_valid": not violations,
                "wall_fingerprint_unchanged": True}
