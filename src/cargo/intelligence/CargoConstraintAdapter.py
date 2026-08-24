from dataclasses import dataclass
from typing import Any,Dict,Tuple
from .CargoProfileEngine import CargoProfileEngine
from .CompressionPolicyEngine import CompressionPolicyEngine
from .FragilityPolicyEngine import FragilityPolicyEngine
from .OrientationPolicyEngine import OrientationPolicyEngine
from .StackPolicyEngine import StackPolicyEngine

@dataclass(frozen=True)
class PreparedCargoIntelligence:
    cargo:Tuple[Any,...]
    profiles:Dict[str,Any]
    constraints:Dict[str,Dict[str,Any]]
    audit:Dict[str,Any]
    def to_dict(self):return {"profiles":{k:v.to_dict() for k,v in self.profiles.items()},"constraints":self.constraints,"audit":self.audit}

class CargoConstraintAdapter:
    """Non-destructive business-policy adapter over authoritative solver constraints."""
    def __init__(self,engine=None):
        self.engine=engine or CargoProfileEngine();self.orientation=OrientationPolicyEngine();self.stack=StackPolicyEngine();self.compression=CompressionPolicyEngine();self.fragility=FragilityPolicyEngine()
    def prepare(self,cargo):
        cargo=tuple(cargo);profiles=self.engine.profile_all(cargo);constraints={};manual=0
        for sku in cargo:
            p=profiles[sku.sku_id];manual+=p.source=="USER_DEFINED"
            constraints[sku.sku_id]={"allowedOrientation":{"base":list(p.orientationPolicy.base),"top":list(p.orientationPolicy.top),"door":list(p.orientationPolicy.door),"forbidden":list(p.orientationPolicy.forbidden)},
                "maxStack":{"base":p.stackPolicy.base_max_layers,"top":p.stackPolicy.top_max_layers},"doorPriority":p.loadingPriority.door_priority,
                "topAllowed":p.stackPolicy.top_allowed,"compressionLimit":p.compressionPolicy.max_load_kg,"fragility":p.fragility,"source":p.source}
        audit={"sku_count":len(cargo),"manual_profiles":manual,"inferred_profiles":len(cargo)-manual,
            "solver_constraints_mutated":False,"user_defined_solver_rules_preserved":True,"adapter_mode":"AUDIT_AND_GATE"}
        return PreparedCargoIntelligence(cargo,profiles,constraints,audit)
    def validate_orientation(self,prepared,sku_id,orientation,context):
        allowed=self.orientation.is_allowed(prepared.profiles[sku_id],orientation,context)
        return allowed,None if allowed else "CARGO_INTELLIGENCE_ORIENTATION_FORBIDDEN"
    def validate_stack(self,prepared,sku_id,current_layers,additional_layers=1,context="TOP_FILL"):
        return self.stack.validate(prepared.profiles[sku_id],current_layers,additional_layers,context)
    def validate_compression(self,prepared,sku_id,top_load_kg):
        p=prepared.profiles[sku_id];ok,reason=self.compression.validate(p,top_load_kg)
        if not ok:return ok,reason
        return self.fragility.validate_support_role(p,top_load_kg)
