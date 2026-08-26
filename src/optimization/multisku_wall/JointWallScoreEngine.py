from .types import JointWallScore


class JointWallScoreEngine:
    @staticmethod
    def metrics(container, placements, wall_ids, detector):
        selected=[p for p in placements if detector.wall_id(p) in wall_ids and p.context.value!="TOP_FILL"]
        if not selected:return {"coverage":0.0,"side_gap":container.Ly,"centered_gap":0.0,"gap":0.0,"incomplete":0,"isolated":0,"sku_count":0,"top":0.0}
        by_wall={wid:[p for p in selected if detector.wall_id(p)==wid] for wid in wall_ids}
        extents=sorted((min(p.min_x for p in ps),max(p.max_x for p in ps)) for ps in by_wall.values() if ps)
        gap=sum(max(0.0,b[0]-a[1]) for a,b in zip(extents,extents[1:]))
        left=min(p.min_y for p in selected);right=container.Ly-max(p.max_y for p in selected)
        layers={round(p.min_z,5) for p in selected};incomplete=0
        for z in layers:
            rows=[p for p in selected if round(p.min_z,5)==z]
            intervals=[]
            for p in sorted(rows,key=lambda p:p.min_y):
                if intervals and p.min_y<=intervals[-1][1]+1e-6:intervals[-1]=(intervals[-1][0],max(intervals[-1][1],p.max_y))
                else:intervals.append((p.min_y,p.max_y))
            if sum(b-a for a,b in intervals)<.90*container.Ly:incomplete+=1
        column_groups={}
        for placement in selected:
            key=(round(placement.min_x,5),round(placement.min_y,5),round(placement.orientation.dx,5),round(placement.orientation.dy,5))
            column_groups.setdefault(key,[]).append(placement)
        isolated=0
        for key,column in column_groups.items():
            if len(column)!=1:continue
            placement=column[0];has_neighbor=False
            for other_key,other_column in column_groups.items():
                if other_key==key:continue
                other=other_column[0]
                x_face=abs(placement.max_x-other.min_x)<1e-5 or abs(other.max_x-placement.min_x)<1e-5
                y_face=abs(placement.max_y-other.min_y)<1e-5 or abs(other.max_y-placement.min_y)<1e-5
                x_overlap=min(placement.max_x,other.max_x)-max(placement.min_x,other.min_x)>1e-5
                y_overlap=min(placement.max_y,other.max_y)-max(placement.min_y,other.min_y)>1e-5
                z_overlap=min(placement.max_z,other.max_z)-max(placement.min_z,other.min_z)>1e-5
                if z_overlap and ((x_face and y_overlap) or (y_face and x_overlap)):
                    has_neighbor=True;break
            isolated+=not has_neighbor
        slab=max(max(p.max_x for p in selected)-min(p.min_x for p in selected),1e-9)*container.Ly*container.Lz
        coverage=sum(p.volume for p in selected)/slab
        top_area=sum(p.orientation.dx*p.orientation.dy for p in selected if not any(abs(q.min_z-p.max_z)<1e-5 and min(p.max_x,q.max_x)-max(p.min_x,q.min_x)>1e-5 and min(p.max_y,q.max_y)-max(p.min_y,q.min_y)>1e-5 for q in selected))
        return {"coverage":coverage,"side_gap":max(0,left)+max(0,right),"centered_gap":max(0,min(left,right)),"gap":gap,"incomplete":incomplete,
                "isolated":isolated,"sku_count":len({p.sku_id for p in selected}),"top":top_area}

    def score(self,before,after):
        coverage=min(100.0,100*after["coverage"]);interface=max(0.0,100-200*after["gap"])
        side=max(0.0,100-100*after["side_gap"]-200*after["centered_gap"]);layer=max(0.0,100-10*after["incomplete"])
        top=min(100.0,50*after["top"]);mix=min(100.0,50*after["sku_count"])
        gap_penalty=100*after["gap"];isolated_penalty=5*after["isolated"]
        final=.20*coverage+.20*interface+.15*side+.15*layer+.15*top+.15*mix-gap_penalty-isolated_penalty
        # A candidate must improve geometry, not merely preserve it under a new ID.
        improvement=(before["gap"]-after["gap"])*100+(before["side_gap"]-after["side_gap"])*20+(before["centered_gap"]-after["centered_gap"])*50+(before["incomplete"]-after["incomplete"])*2+(before["isolated"]-after["isolated"])
        return JointWallScore(round(coverage,4),round(interface,4),round(side,4),round(layer,4),round(top,4),round(mix,4),
                              round(gap_penalty,4),round(isolated_penalty,4),round(final+improvement,4))
