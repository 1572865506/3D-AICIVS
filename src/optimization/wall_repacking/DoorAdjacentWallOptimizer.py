class DoorAdjacentWallOptimizer:
    def evaluate(self,walls,door_start):
        if not walls:return {"ready":False,"reason":"NO_WALL"}
        wall=min(walls,key=lambda w:abs(w.x_range[1]-door_start))
        stable=bool(wall.columns) and min((c.height for c in wall.columns),default=0)>0
        return {"ready":stable,"wall_id":wall.wall_id,"gap_m":round(max(0,door_start-wall.x_range[1]),6),"stable":stable}
