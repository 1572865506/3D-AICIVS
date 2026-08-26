from .types import WallChain,WallConnection

class WallChainGraph:
    def build(self,cargo_walls,transition_walls,door_wall,container):
        nodes=[]
        for w in cargo_walls:nodes.append({"id":w.id,"role":w.role,"x_start":w.x_start,"x_end":w.x_end,"coverage":w.continuity["coverage"]})
        for w in transition_walls:nodes.append({"id":w.id,"role":"TRANSITION_WALL","x_start":w.x_range[0],"x_end":w.x_range[1],"coverage":w.coverage})
        if door_wall and getattr(door_wall, 'placements', None):
            door_coverage=door_wall.coverage
            nodes.append({"id":door_wall.wall_id,"role":"DOOR_WALL","x_start":min(p.x for p in door_wall.placements),"x_end":max(p.max_x for p in door_wall.placements),"coverage":door_coverage})
        nodes.sort(key=lambda n:n["x_start"]);connections=[];weak=[];broken=[]
        for left,right in zip(nodes,nodes[1:]):
            gap=max(0.0,right["x_start"]-left["x_end"]);overlap=min(left["coverage"],right["coverage"])
            strength=max(0.0,100.0*(1-gap/.03))*overlap if gap<=.03 else 0.0
            edge=WallConnection(left["id"],right["id"],round(gap,6),round(overlap,6),round(strength,4));connections.append(edge)
            label=f"{left['id']}->{right['id']}"
            if gap>.03 or strength<60:weak.append(label)
            if gap>.03:broken.append(label)
        length=max(n["x_end"] for n in nodes)-min(n["x_start"] for n in nodes) if nodes else 0.0
        return WallChain(tuple(nodes),tuple(connections),round(length,6),tuple(weak),tuple(broken),not broken)
