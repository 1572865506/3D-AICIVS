class DoorSealOptimizer:
    """Measures the frozen door/transition interface without rewriting the Door Wall."""

    def analyze(self, container, door_wall, wall_optimization):
        has_door = door_wall and getattr(door_wall, 'placements', None)
        door_start = min((p.x for p in door_wall.placements), default=container.Lx) if has_door else container.Lx
        structural_end = wall_optimization.optimized_wall_end_x if wall_optimization else 0.0
        gap = max(0.0, door_start - structural_end)
        zone_depth = max(getattr(container, 'door_zone_length_m', 1.2), 1e-12)
        longitudinal = 100.0 * max(0.0, 1.0 - gap / zone_depth)
        cross_section = 100.0 * door_wall.coverage if has_door else 100.0
        stable = bool(door_wall.stability.stable) if has_door and hasattr(door_wall, 'stability') else True
        continuity = round(door_wall.continuity.continuity_score, 4) if has_door and hasattr(door_wall, 'continuity') else 100.0
        return {
            "status": "READY" if longitudinal >= 95.0 and stable else "FAILED",
            "door_coverage": round(longitudinal, 4),
            "longitudinal_seal_coverage": round(longitudinal, 4),
            "frozen_cross_section_coverage": round(cross_section, 4),
            "target_coverage": 95.0,
            "gap_m": round(gap, 6),
            "continuity": continuity,
            "stability": stable,
            "door_wall_unchanged": True,
            "cross_section_locked": True,
        }
