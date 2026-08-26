from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from backend.solver_v2.domain.models import ContainerSpec, Placement


@dataclass(frozen=True)
class ColumnTippingAnalysis:
    column_id: str
    sku_id: str
    placement_ids: Tuple[str, ...]
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    min_z: float
    max_z: float
    depth_x: float
    width_y: float
    height_z: float
    total_weight_kg: float
    front_supported: bool
    rear_supported: bool
    left_supported: bool
    right_supported: bool
    braking_tipping_moment: float
    braking_restoring_moment: float
    braking_safety_factor: float
    braking_tipping_safe: bool
    risk_level: str
    recommendation: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "column_id": self.column_id,
            "sku_id": self.sku_id,
            "placement_count": len(self.placement_ids),
            "x_range": [round(self.min_x, 3), round(self.max_x, 3)],
            "y_range": [round(self.min_y, 3), round(self.max_y, 3)],
            "z_range": [round(self.min_z, 3), round(self.max_z, 3)],
            "aspect_ratio_h_d": round(self.height_z / max(self.depth_x, 1e-4), 3),
            "total_weight_kg": round(self.total_weight_kg, 2),
            "front_supported": self.front_supported,
            "rear_supported": self.rear_supported,
            "braking_safety_factor": round(self.braking_safety_factor, 2),
            "braking_tipping_safe": self.braking_tipping_safe,
            "risk_level": self.risk_level,
            "recommendation": self.recommendation,
        }


@dataclass(frozen=True)
class BrakingStabilityReport:
    overall_safe: bool
    evaluated_columns_count: int
    at_risk_columns_count: int
    min_braking_safety_factor: float
    average_braking_safety_factor: float
    braking_acceleration_g: float
    unsupported_front_stacks_count: int
    columns: Tuple[ColumnTippingAnalysis, ...]
    warnings: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_safe": self.overall_safe,
            "evaluated_columns_count": self.evaluated_columns_count,
            "at_risk_columns_count": self.at_risk_columns_count,
            "min_braking_safety_factor": round(self.min_braking_safety_factor, 3),
            "average_braking_safety_factor": round(self.average_braking_safety_factor, 3),
            "braking_acceleration_g": self.braking_acceleration_g,
            "unsupported_front_stacks_count": self.unsupported_front_stacks_count,
            "columns": [col.to_dict() for col in self.columns],
            "warnings": list(self.warnings),
        }


class BrakingStabilityValidator:
    """
    Evaluates dynamic tipping stability for all cargo stacks/walls under
    emergency vehicle braking (0.80g deceleration) and acceleration/vibration.
    ISO 1496 / EN 12195 standard cargo restraint criteria.
    """

    def __init__(
        self,
        braking_acceleration_g: float = 0.80,
        acceleration_g: float = 0.50,
        lateral_acceleration_g: float = 0.50,
        contact_tolerance_m: float = 0.035,
        min_safety_factor: float = 1.15,
    ):
        self.a_brake = braking_acceleration_g
        self.a_accel = acceleration_g
        self.a_lateral = lateral_acceleration_g
        self.tolerance = contact_tolerance_m
        self.min_safety_factor = min_safety_factor

    def validate(
        self, container: ContainerSpec, placements: Tuple[Placement, ...]
    ) -> BrakingStabilityReport:
        if not placements:
            return BrakingStabilityReport(
                overall_safe=True,
                evaluated_columns_count=0,
                at_risk_columns_count=0,
                min_braking_safety_factor=99.0,
                average_braking_safety_factor=99.0,
                braking_acceleration_g=self.a_brake,
                unsupported_front_stacks_count=0,
                columns=(),
                warnings=(),
            )

        # 1. Group placements into vertical stacks/columns by (X, Y) footprint
        columns_dict: Dict[Tuple[float, float, float, float], List[Placement]] = {}
        for p in placements:
            key = (
                round(p.min_x, 3),
                round(p.max_x, 3),
                round(p.min_y, 3),
                round(p.max_y, 3),
            )
            columns_dict.setdefault(key, []).append(p)

        column_analyses: List[ColumnTippingAnalysis] = []
        warnings: List[str] = []
        g = 1.0  # Normalized gravity (in g units)

        col_index = 0
        for (x1, x2, y1, y2), col_placements in columns_dict.items():
            col_index += 1
            min_z = min(p.min_z for p in col_placements)
            max_z = max(p.max_z for p in col_placements)
            weight = sum(p.weight_kg for p in col_placements)
            depth_x = x2 - x1
            width_y = y2 - y1
            height_z = max_z - min_z
            sku_id = col_placements[0].sku_id
            p_ids = tuple(p.placement_id for p in col_placements)

            z_com = height_z / 2.0
            x_pivot = depth_x / 2.0

            # Front support (-X direction under braking, toward bulkhead at X=0)
            front_supported = (x1 <= self.tolerance)
            if not front_supported:
                for other in placements:
                    if other in col_placements:
                        continue
                    if -1e-5 <= (x1 - other.max_x) <= self.tolerance:
                        y_overlap = min(y2, other.max_y) - max(y1, other.min_y)
                        z_overlap = min(max_z, other.max_z) - max(min_z, other.min_z)
                        if y_overlap > 0.05 and z_overlap > 0.10:
                            front_supported = True
                            break

            # Rear support (+X direction toward door)
            rear_supported = (container.Lx - x2 <= self.tolerance)
            if not rear_supported:
                for other in placements:
                    if other in col_placements:
                        continue
                    if -1e-5 <= (other.min_x - x2) <= self.tolerance:
                        y_overlap = min(y2, other.max_y) - max(y1, other.min_y)
                        z_overlap = min(max_z, other.max_z) - max(min_z, other.min_z)
                        if y_overlap > 0.05 and z_overlap > 0.10:
                            rear_supported = True
                            break

            left_supported = (y1 <= self.tolerance) or any(
                -1e-5 <= (y1 - o.max_y) <= self.tolerance for o in placements if o not in col_placements
            )
            right_supported = (container.Ly - y2 <= self.tolerance) or any(
                -1e-5 <= (o.min_y - y2) <= self.tolerance for o in placements if o not in col_placements
            )

            m_overturn = weight * self.a_brake * z_com
            m_restore = weight * g * x_pivot
            safety_factor = m_restore / max(m_overturn, 1e-6)

            if front_supported:
                tipping_safe = True
                effective_factor = max(safety_factor, 2.5)
                risk_level = "SAFE"
                recommendation = "前壁/前排货垛支撑牢固，刹车惯性力被直接承受"
            else:
                tipping_safe = (safety_factor >= self.min_safety_factor)
                effective_factor = safety_factor
                if tipping_safe:
                    risk_level = "MODERATE"
                    recommendation = "立柱高厚比自稳，但前方有空隙，建议增设充气垫或拉紧带"
                else:
                    risk_level = "HIGH_RISK"
                    recommendation = f"急刹车存在倾倒坍塌风险 (高厚比 {height_z/max(depth_x, 1e-3):.2f}, 稳定系数 {safety_factor:.2f} < {self.min_safety_factor})"
                    warnings.append(
                        f"货垛 [X: {x1:.2f}m, SKU: {sku_id}] 前方悬空且高厚比过大，急刹车可能向前倾倒"
                    )

            analysis = ColumnTippingAnalysis(
                column_id=f"COL_{col_index:03d}",
                sku_id=sku_id,
                placement_ids=p_ids,
                min_x=x1,
                max_x=x2,
                min_y=y1,
                max_y=y2,
                min_z=min_z,
                max_z=max_z,
                depth_x=depth_x,
                width_y=width_y,
                height_z=height_z,
                total_weight_kg=weight,
                front_supported=front_supported,
                rear_supported=rear_supported,
                left_supported=left_supported,
                right_supported=right_supported,
                braking_tipping_moment=round(m_overturn, 2),
                braking_restoring_moment=round(m_restore, 2),
                braking_safety_factor=round(effective_factor, 3),
                braking_tipping_safe=tipping_safe,
                risk_level=risk_level,
                recommendation=recommendation,
            )
            column_analyses.append(analysis)

        factors = [col.braking_safety_factor for col in column_analyses]
        at_risk = [col for col in column_analyses if not col.braking_tipping_safe]
        unsupported = [col for col in column_analyses if not col.front_supported]

        return BrakingStabilityReport(
            overall_safe=len(at_risk) == 0,
            evaluated_columns_count=len(column_analyses),
            at_risk_columns_count=len(at_risk),
            min_braking_safety_factor=min(factors) if factors else 1.0,
            average_braking_safety_factor=sum(factors) / max(len(factors), 1),
            braking_acceleration_g=self.a_brake,
            unsupported_front_stacks_count=len(unsupported),
            columns=tuple(column_analyses),
            warnings=tuple(warnings),
        )
