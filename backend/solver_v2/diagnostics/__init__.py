"""几何诊断导出包（结构审计任务 §3 规范落位 + 观感体检）。"""
from backend.solver_v2.diagnostics.export import export_diagnostics_bundle
from backend.solver_v2.diagnostics.geometry_qa import compute_geometry_qa

__all__ = ["export_diagnostics_bundle", "compute_geometry_qa"]
