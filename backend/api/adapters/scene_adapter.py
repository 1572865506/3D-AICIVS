"""Canonical backend coordinates -> directly renderable Three.js scene data."""


class SceneAdapter:
    @staticmethod
    def scene(cargo,container):
        objects=[]
        for item in cargo:
            p=item["position"]
            occupied=item.get("occupiedDimensions")
            s=({"w":occupied["width"],"d":occupied["depth"],"h":occupied["height"]}
               if occupied else item["size"])
            objects.append({"uuid":item["id"],"type":"CARGO",
                "position":[p["x"]+s["w"]/2,p["y"]+s["d"]/2,p["z"]+s["h"]/2],
                "scale":[s["w"],s["d"],s["h"]],"rotation":[0,0,0],
                "style":{"color":item["material"]["color"],"opacity":1.0},
                "metadata":{"sku":item["sku"],"step":item["loading"]["step"],"wall":item["loading"]["wall"],
                            "orientation":item.get("rotation",{}).get("orientation","UPRIGHT_NORMAL")}})
        return {"coordinate_space":"solver_canonical_center","objects":objects,
                "container_style":{"mode":"xray","opacity":.25,"visible_faces":["roof","door","near_side"]},
                "container_bounds":{"min":[0,0,0],"max":[container.Lx,container.Ly,container.Lz]}}

    @staticmethod
    def camera(container):
        span=max(container.Lx,container.Ly,container.Lz)
        return {"view":"isometric","position":[container.Lx*1.25,container.Ly+span*.55,container.Lz+span*.4],
                "target":[container.Lx/2,container.Ly/2,container.Lz/2],"zoom":1.2,
                "up":[0,0,1],"coordinate_space":"solver_canonical"}

    @staticmethod
    def highlight(cargo,walls,sequence,kind,value):
        if kind=="sku":ids=[x["id"] for x in cargo if x["sku"]==value]
        elif kind=="wall":ids=next((w["placements"] for w in walls if w["id"]==value),[])
        elif kind=="step":ids=next((s["placements"] for s in sequence["steps"] if str(s["step"])==str(value)),[])
        else:ids=[value] if any(x["id"]==value for x in cargo) else []
        return {"highlight":ids,"color":"#FFAA00","selector":{"type":kind,"value":value}}
