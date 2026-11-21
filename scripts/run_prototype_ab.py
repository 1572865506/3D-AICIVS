"""
双货单（case_52 40HQ & case_53 20GP）A/B/C 原型对比评测脚本。

对比组：
  (A) 当前生产 UnifiedSolver
  (B) 双向汇合 + EMS 新原型（遵守 adapter.py 默认朝向）
  (C) 双向汇合 + EMS 新原型（flexible_unspecified=True，未锁立放普通纸箱开放 6 向旋转）
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, List, Tuple

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.solver_v2 import solve as solve_v2
from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.domain.models import CargoSKU, ContainerSpec
from backend.solver_v2.solver.bidirectional_ems_prototype import (
    build_flexible_cargo_list,
    solve_bidirectional_ems,
)
from backend.solver_v2.validation.delivery_gate import evaluate_delivery
from backend.solver_v2.diagnostics.geometry_qa import compute_geometry_qa


def _load_case(path: str) -> Tuple[str, ContainerSpec, List[CargoSKU]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    container = InputAdapter.parse_container(data["container"])
    cargo = InputAdapter.parse_cargo_list(data["cargo"])
    return data.get("case_id", os.path.basename(path)), container, cargo


def _extract_metrics(
    sol: Any,
    cargo_list: List[CargoSKU],
    container: ContainerSpec,
    elapsed_s: float,
) -> Dict[str, Any]:
    placements = list(getattr(sol, "placements", []) or [])
    packed_vol = sum(p.volume for p in placements)
    util_pct = 100.0 * packed_vol / max(1e-9, container.volume)

    placed_cnt: Dict[str, int] = {}
    for p in placements:
        placed_cnt[p.sku_id] = placed_cnt.get(p.sku_id, 0) + 1

    total_skus = len(cargo_list)
    completed_skus = sum(1 for s in cargo_list if placed_cnt.get(s.sku_id, 0) >= s.quantity.required)
    starved_skus = sum(1 for s in cargo_list if s.quantity.required > 0 and placed_cnt.get(s.sku_id, 0) == 0)

    val = getattr(sol, "validation_result", None)
    violations = len(getattr(val, "violations", []) or [])
    collisions = int(getattr(val, "overlap_pair_count", 0) or 0)

    qa = getattr(getattr(sol, "telemetry", None), "geometry_qa", None)
    if qa is None:
        qa = compute_geometry_qa(container, placements)
    cavity_pct = float(qa.get("bbox_void_ratio_pct", 0.0))

    dg = evaluate_delivery(sol, cargo_list, container=container, geometry_qa=qa)
    return {
        "vol_m3": round(packed_vol, 3),
        "util_pct": round(util_pct, 2),
        "cavity_pct": round(cavity_pct, 2),
        "completed": f"{completed_skus}/{total_skus}",
        "placed_boxes": f"{len(placements)}/{sum(s.quantity.required for s in cargo_list)}",
        "starved": starved_skus,
        "violations": violations,
        "collisions": collisions,
        "time_s": round(elapsed_s, 2),
        "dg": dg.get("verdict", "UNKNOWN"),
    }


def _run_case(case_path: str) -> None:
    cid, container, cargo = _load_case(case_path)
    print(f"\n=== {cid} ({container.Lx:.3f}x{container.Ly:.3f}x{container.Lz:.3f}m, {container.volume:.2f}m3) ===")

    # (A) UnifiedSolver
    t0 = time.time()
    sol_a = solve_v2(container, cargo)
    m_a = _extract_metrics(sol_a, cargo, container, time.time() - t0)

    # (B) Bidirectional + EMS (默认朝向)
    t0 = time.time()
    sol_b = solve_bidirectional_ems(container, cargo, flexible_unspecified=False)
    m_b = _extract_metrics(sol_b, cargo, container, time.time() - t0)

    # (C) Bidirectional + EMS (flexible_unspecified=True)
    t0 = time.time()
    sol_c = solve_bidirectional_ems(container, cargo, flexible_unspecified=True)
    flex_cargo = build_flexible_cargo_list(cargo)
    m_c = _extract_metrics(sol_c, flex_cargo, container, time.time() - t0)

    for label, m in [("A-UnifiedSolver", m_a), ("B-Proto(Default)", m_b), ("C-Proto(Flex6)", m_c)]:
        print(
            f"  [{label:<16}] 体积={m['vol_m3']:>6.3f}m3 | 利用率={m['util_pct']:>5.2f}% | "
            f"空腔={m['cavity_pct']:>5.2f}% | 完单SKU={m['completed']:>6} | 箱数={m['placed_boxes']:>9} | "
            f"饥饿={m['starved']} | 违规={m['violations']} | 碰撞={m['collisions']} | "
            f"耗时={m['time_s']:>5.2f}s | DG={m['dg']}"
        )


def main() -> None:
    cases = [
        os.path.join(REPO_ROOT, "tests", "cases", "case_52_real_81sku_40hq.json"),
        os.path.join(REPO_ROOT, "tests", "cases", "case_53_real_singpc_20gp.json"),
    ]
    for p in cases:
        _run_case(p)


if __name__ == "__main__":
    main()
