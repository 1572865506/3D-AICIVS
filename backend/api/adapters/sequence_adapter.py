"""Loading plan -> animation-safe product sequence."""


class SequenceAdapter:
    @staticmethod
    def sequence(plan,repair_groups):
        target_group={g.placement_ids[0]:g for g in repair_groups if g.placement_ids}
        steps=[]
        for step in plan.steps:
            group=next((target_group[pid] for pid in step.placement_ids if pid in target_group),None)
            steps.append({"step":step.step_index,"action":step.action,"placements":list(step.placement_ids),
                          "phase":"REPAIR" if group else step.phase,"original_phase":step.phase,
                          "group":({"id":group.id,"type":group.type,"reason":group.reason,
                                    "objects":list(group.placement_ids)} if group else None),
                          "wall":step.wall_id,"row":step.row_id,"layer":step.layer_id})
        return {"feasible":plan.sequence_feasible,"steps":steps,"total_steps":len(steps),
                "loading_mode":"MANUAL_CARTON","deterministic_signature":plan.metrics.get("sequence_signature")}

    @staticmethod
    def animation(plan,placement_map,container):
        frames=[]
        for step in plan.steps:
            movements=[]
            for index,pid in enumerate(step.placement_ids):
                p=placement_map[pid];path=step.insertion_paths[min(index,len(step.insertion_paths)-1)]
                movements.append({"object":pid,
                    "from":[path["start_x"]+p.orientation.dx/2,p.position.y+p.orientation.dy/2,p.position.z+p.orientation.dz/2],
                    "to":[p.position.x+p.orientation.dx/2,p.position.y+p.orientation.dy/2,p.position.z+p.orientation.dz/2]})
            first=movements[0] if movements else {"from":[container.Lx,0,0],"to":[container.Lx,0,0]}
            frames.append({"step":step.step_index,"objects":list(step.placement_ids),"from":first["from"],"to":first["to"],
                           "movements":movements,"duration":2.0,"coordinate_space":"solver_canonical_center"})
        return {"frames":frames,"total_frames":len(frames),"playback":"sequential"}
