from backend.solver_v2.geometry.aabb import AABB
class TopPlacementValidator:
    def validate(self,placement,container,existing,support_state):
        if not support_state.valid:return False,support_state.reason
        a=AABB.from_placement(placement)
        if not a.is_within_bounds(container.Lx,container.Ly,container.Lz):return False,"TOP_OOB"
        # A TopRegion is only a coarse envelope.  Mixed-SKU walls can have a
        # stepped real top surface, so prove contact against actual cartons at
        # this exact Z before collision validation.  The final global validator
        # remains authoritative and uses the same physical contact definition.
        if placement.min_z>1e-4:
            contact=0.0
            for other in existing:
                if abs(other.max_z-placement.min_z)>1e-4:continue
                ox=max(0.0,min(placement.max_x,other.max_x)-max(placement.min_x,other.min_x))
                oy=max(0.0,min(placement.max_y,other.max_y)-max(placement.min_y,other.min_y))
                contact+=ox*oy
            if contact/max(placement.orientation.dx*placement.orientation.dy,1e-9)<.8-1e-4:
                return False,"INSUFFICIENT_EXACT_TOP_SUPPORT"
        for other in existing:
            b=AABB.from_placement(other)
            if a.penetration_volume(b)>1e-12:return False,"TOP_COLLISION"
        return True,None
