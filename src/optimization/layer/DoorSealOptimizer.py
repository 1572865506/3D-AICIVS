class DoorSealOptimizer:
    """Measures the frozen door/transition interface without rewriting the Door Wall."""

    def analyze(self, container, door_wall, wall_optimization):
        door_start = min((p.x for p in door_wall.placements), default=container.Lx)
        structural_end = wall_optimization.optimized_wall_end_x
        gap = max(0.0, door_start - structural_end)
        zone_depth = max(container.door_zone_length_m, 1e-12)
        longitudinal = 100.0 * max(0.0, 1.0 - gap / zone_depth)
        cross_section = 100.0 * door_wall.coverage
        stable = bool(door_wall.stability.stable)
        return {
            "status": "READY" if longitudinal >= 95.0 and stable else "FAILED",
            "door_coverage": round(longitudinal, 4),
            "longitudinal_seal_coverage": round(longitudinal, 4),
            "frozen_cross_section_coverage": round(cross_section, 4),
            "target_coverage": 95.0,
            "gap_m": round(gap, 6),
            "continuity": round(door_wall.continuity.continuity_score, 4),
            "stability": stable,
            "door_wall_unchanged": True,
            "cross_section_locked": True,
        }
