"""
Solver V2 Validation Types and Data Structures.
Defines violation classifications, error models, and independent validation results.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional, Tuple


class ViolationType(str, Enum):
    OUT_OF_BOUNDS = "OUT_OF_BOUNDS"
    COLLISION_OVERLAP = "COLLISION_OVERLAP"
    PAYLOAD_EXCEEDED = "PAYLOAD_EXCEEDED"
    FORBIDDEN_ORIENTATION = "FORBIDDEN_ORIENTATION"
    ZONE_VIOLATION = "ZONE_VIOLATION"
    DOOR_LOCKOUT_VIOLATION = "DOOR_LOCKOUT_VIOLATION"
    FLOOR_ONLY_VIOLATION = "FLOOR_ONLY_VIOLATION"
    STACK_LIMIT_VIOLATION = "STACK_LIMIT_VIOLATION"
    NO_TOP_STACK_VIOLATION = "NO_TOP_STACK_VIOLATION"
    INSUFFICIENT_SUPPORT = "INSUFFICIENT_SUPPORT"
    BEARING_EXCEEDED = "BEARING_EXCEEDED"
    PRESSURE_EXCEEDED = "PRESSURE_EXCEEDED"
    QUANTITY_VIOLATION = "QUANTITY_VIOLATION"
    UNKNOWN_SKU = "UNKNOWN_SKU"
    CAVITY_THRESHOLD_EXCEEDED = "CAVITY_THRESHOLD_EXCEEDED"
    UNRESOLVED_DEBT = "UNRESOLVED_DEBT"
    UNSTABLE_PLACEMENT = "UNSTABLE_PLACEMENT"


class ViolationSeverity(str, Enum):
    FATAL = "FATAL"        # Hard violation: solution is strictly rejected (is_valid = False)
    WARNING = "WARNING"    # Soft violation or metric advisory


@dataclass
class ViolationDetail:
    """Detailed record of a single validation violation."""
    violation_type: ViolationType
    severity: ViolationSeverity
    message: str
    sku_id: Optional[str] = None
    placement_id: Optional[str] = None
    placement_index: Optional[int] = None
    location: Optional[Tuple[float, float, float]] = None
    dimension: Optional[Tuple[float, float, float]] = None
    extra_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.violation_type.value,
            "severity": self.severity.value,
            "message": self.message,
            "sku_id": self.sku_id,
            "placement_id": self.placement_id,
            "placement_index": self.placement_index,
            "location": self.location,
            "dimension": self.dimension,
            "extra_data": self.extra_data,
        }


@dataclass
class ValidationResult:
    """
    Comprehensive validation report produced by IndependentGlobalValidator.
    Supports both attribute access and dict-style indexing for 100% backward compatibility.
    """
    is_valid: bool
    rejection_reasons: List[str] = field(default_factory=list)
    violations: List[ViolationDetail] = field(default_factory=list)

    # Detailed categorizations for fast inspection
    bounds_violations: List[ViolationDetail] = field(default_factory=list)
    overlap_violations: List[ViolationDetail] = field(default_factory=list)
    orientation_violations: List[ViolationDetail] = field(default_factory=list)
    constraint_violations: List[ViolationDetail] = field(default_factory=list)
    stability_violations: List[ViolationDetail] = field(default_factory=list)
    quantity_violations: List[ViolationDetail] = field(default_factory=list)

    # Metrics
    metrics: Dict[str, Any] = field(default_factory=dict)
    summary: str = ""

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        if key in self.metrics:
            return self.metrics[key]
        raise KeyError(f"'{key}' not found in ValidationResult or metrics")

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) or (key in self.metrics)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "is_valid": self.is_valid,
            "rejection_reasons": self.rejection_reasons,
            "summary": self.summary,
            "violation_count": len(self.violations),
            "violations": [v.to_dict() for v in self.violations],
            "bounds_violations": [v.to_dict() for v in self.bounds_violations],
            "overlap_violations": [v.to_dict() for v in self.overlap_violations],
            "orientation_violations": [v.to_dict() for v in self.orientation_violations],
            "constraint_violations": [v.to_dict() for v in self.constraint_violations],
            "stability_violations": [v.to_dict() for v in self.stability_violations],
            "quantity_violations": [v.to_dict() for v in self.quantity_violations],
            "metrics": self.metrics,
        }
        d.update(self.metrics)
        return d
