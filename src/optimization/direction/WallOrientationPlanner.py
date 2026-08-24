class WallOrientationPlanner:
    def select(self, candidates, rule):
        legal = [c for c in candidates if c.facing not in rule.forbidden_facing]
        legal.sort(key=lambda c: (-c.score.final_score, c.facing, c.orientation))
        return legal[0] if legal else None

    @staticmethod
    def continuity(selected):
        values = [c.facing for c in selected]
        if not values:
            return 0.0
        majority = max(values.count(value) for value in set(values))
        return round(100.0 * majority / len(values), 4)
