from .types import LayerGap
class LayerOccupancyMap:
    def __init__(self,resolution=.2):self.resolution=resolution
    def build(self,container,placements,z0,z1,layer_id):
        import math
        nx=math.ceil(container.Lx/self.resolution);ny=math.ceil(container.Ly/self.resolution);occupied=set()
        for p in placements:
            if min(p.max_z,z1)-max(p.min_z,z0)<=1e-9:continue
            for ix in range(max(0,int(p.min_x/self.resolution)),min(nx,math.ceil(p.max_x/self.resolution))):
                for iy in range(max(0,int(p.min_y/self.resolution)),min(ny,math.ceil(p.max_y/self.resolution))):occupied.add((ix,iy))
        empty={(ix,iy) for ix in range(nx) for iy in range(ny) if (ix,iy) not in occupied};seen=set();gaps=[]
        for seed in sorted(empty):
            if seed in seen:continue
            stack=[seed];seen.add(seed);cells=[]
            while stack:
                cell=stack.pop();cells.append(cell);ix,iy=cell
                for nxt in ((ix-1,iy),(ix+1,iy),(ix,iy-1),(ix,iy+1)):
                    if nxt in empty and nxt not in seen:seen.add(nxt);stack.append(nxt)
            xs=[c[0] for c in cells];ys=[c[1] for c in cells];x=min(xs)*self.resolution;y=min(ys)*self.resolution
            dx=min(container.Lx,(max(xs)+1)*self.resolution)-x;dy=min(container.Ly,(max(ys)+1)*self.resolution)-y;dz=z1-z0
            gaps.append(LayerGap(f"{layer_id}_GAP_{len(gaps)+1:03d}",layer_id,x,y,z0,dx,dy,dz,round(len(cells)*self.resolution*self.resolution*dz,6),z0==0))
        return {"occupied":occupied,"empty":empty,"gaps":tuple(gaps),"nx":nx,"ny":ny}
