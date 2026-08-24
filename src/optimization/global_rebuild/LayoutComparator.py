class LayoutComparator:
    def compare(self,old,new):
        return {"old_layout":old.layout_id,"new_layout":new.layout_id,
                "old_score":old.score.global_score,"new_score":new.score.global_score,
                "score_delta":round(new.score.global_score-old.score.global_score,4),
                "utilization_delta_pct_points":round(new.score.volume_efficiency-old.score.volume_efficiency,4),
                "wall_order_changed":old.wall_plan.wall_order!=new.wall_plan.wall_order,
                "direction_effective":new.score.direction_compliance>=old.score.direction_compliance and new.wall_plan.reconstructed}
