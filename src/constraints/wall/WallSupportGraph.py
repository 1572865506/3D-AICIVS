from typing import Dict, Iterable, Tuple

from backend.solver_v2.physics.support_graph import SupportGraph
from .types import SupportLink


class WallSupportGraph:
    def build(self, container, placements: Iterable) -> Dict:
        placements = tuple(placements)
        graph = SupportGraph(container)
        links = []
        neighbors = {p.placement_id: set() for p in placements}
        committed = []
        for placement in sorted(placements, key=lambda p: (p.min_z, p.min_y)):
            for edge in graph.add_placement(placement, committed):
                links.append(SupportLink(edge.upper_id, edge.lower_id, "SUPPORT", edge.contact_area, edge.support_ratio))
                if edge.lower_id != "FLOOR":
                    neighbors[edge.upper_id].add(edge.lower_id); neighbors[edge.lower_id].add(edge.upper_id)
            for other in committed:
                x_overlap = min(placement.max_x, other.max_x) - max(placement.min_x, other.min_x)
                z_overlap = min(placement.max_z, other.max_z) - max(placement.min_z, other.min_z)
                lateral = abs(placement.min_y-other.max_y)<=1e-6 or abs(placement.max_y-other.min_y)<=1e-6
                if lateral and x_overlap > 1e-9 and z_overlap > 1e-9:
                    area=x_overlap*z_overlap
                    links.append(SupportLink(placement.placement_id, other.placement_id, "CONTACT", area, 1.0))
                    neighbors[placement.placement_id].add(other.placement_id); neighbors[other.placement_id].add(placement.placement_id)
            committed.append(placement)
        isolated = tuple(pid for pid, peers in neighbors.items() if not peers)
        weak = tuple(pid for pid in isolated if next(p for p in placements if p.placement_id==pid).min_z > 1e-9)
        return {"supportLinks": tuple(links), "isolatedCargo": isolated, "weakArea": weak,
                "supportScore": round(100.0 * (1.0-len(isolated)/max(len(placements),1)),4)}
