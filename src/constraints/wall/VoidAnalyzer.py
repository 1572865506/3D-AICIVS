from typing import Iterable, Tuple

from .types import VoidRegion


class WallVoidAnalyzer:
    """Finds internal Y/Z wall gaps; exterior top/edge residuals remain future free space."""
    def analyze(self, placements: Iterable, resolution: float = 0.05) -> Tuple[VoidRegion, ...]:
        placements=tuple(placements)
        if not placements:return ()
        x0=min(p.min_x for p in placements);x1=max(p.max_x for p in placements)
        y1=max(p.max_y for p in placements);z1=max(p.max_z for p in placements)
        ny=max(1,int(round(y1/resolution)));nz=max(1,int(round(z1/resolution)))
        occupied=set()
        for p in placements:
            for iy in range(int(p.min_y/resolution),int(round(p.max_y/resolution))):
                for iz in range(int(p.min_z/resolution),int(round(p.max_z/resolution))):occupied.add((iy,iz))
        empty={(iy,iz) for iy in range(ny) for iz in range(nz) if (iy,iz) not in occupied}
        regions=[];seen=set()
        for seed in sorted(empty):
            if seed in seen:continue
            stack=[seed];seen.add(seed);cells=[];touches_edge=False
            while stack:
                cell=stack.pop();cells.append(cell);iy,iz=cell
                touches_edge |= iy in (0,ny-1) or iz==nz-1
                for nxt in ((iy-1,iz),(iy+1,iz),(iy,iz-1),(iy,iz+1)):
                    if nxt in empty and nxt not in seen:seen.add(nxt);stack.append(nxt)
            if touches_edge:continue
            ys=[c[0] for c in cells];zs=[c[1] for c in cells]
            dims=(x1-x0,(max(ys)-min(ys)+1)*resolution,(max(zs)-min(zs)+1)*resolution)
            volume=len(cells)*resolution*resolution*(x1-x0)
            kind="SMALL_GAP" if volume<0.02 else "BRIDGE_VOID" if min(zs)>0 else "STRUCTURAL_VOID"
            regions.append(VoidRegion(f"VOID_{len(regions)+1:03d}",(x0,min(ys)*resolution,min(zs)*resolution),dims,round(volume,6),kind))
        return tuple(regions)
