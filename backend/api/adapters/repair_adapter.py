"""Repair engine -> frontend group model."""


class RepairAdapter:
    @staticmethod
    def adapt(repair_result):
        if repair_result is None:return {"enabled":False,"repaired":False,"groups":[],"actions":[]}
        return {"enabled":True,"repaired":repair_result.repaired,
                "groups":[{"id":g.id,"type":g.type,"objects":list(g.placement_ids),"reason":g.reason,
                           "created_by":g.created_by,"temporary_stability_resolved":g.stability_after}
                          for g in repair_result.groups],
                "actions":[a.to_dict() for a in repair_result.repair_actions],
                "validation":repair_result.validation_result}
