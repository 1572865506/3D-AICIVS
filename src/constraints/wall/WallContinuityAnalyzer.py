from typing import Dict, Iterable


class WallContinuityAnalyzer:
    def analyze(self, placements: Iterable, container_width: float) -> Dict[str, float]:
        placements = tuple(placements)
        # Mixed-SKU walls do not necessarily share identical carton heights.
        # Measure the physical Y-Z wall surface by horizontal bands bounded by
        # every carton top/bottom, rather than treating equal min_z values as a
        # semantic layer.  This keeps tail-stock composition honest: a shorter
        # neighboring carton produces a top gap instead of a false layer break.
        z_edges = sorted({round(v, 6) for p in placements for v in (p.min_z,p.max_z)})
        total_covered = 0.0
        total_area = 0.0
        gaps = []
        for z0,z1 in zip(z_edges,z_edges[1:]):
            band_height=z1-z0
            if band_height<=1e-9:continue
            mid=(z0+z1)/2
            intervals = sorted((p.min_y, p.max_y) for p in placements if p.min_z<=mid+1e-9 and p.max_z>=mid-1e-9)
            cursor = 0.0
            covered = 0.0
            for start, end in intervals:
                if start > cursor + 1e-9: gaps.append(start - cursor)
                covered += max(0.0, end - max(start, cursor))
                cursor = max(cursor, end)
            if cursor < container_width - 1e-9: gaps.append(container_width - cursor)
            total_covered += min(container_width, covered)*band_height
            total_area += container_width*band_height
        coverage = total_covered / max(total_area, 1e-9)
        largest = max(gaps, default=0.0)
        score = max(0.0, 100.0 * coverage - 30.0 * largest / max(container_width, 1e-9))
        return {"coverage": round(coverage, 6), "gapCount": len([g for g in gaps if g > 1e-9]),
                "largestGap": round(largest, 6), "continuityScore": round(score, 4)}
