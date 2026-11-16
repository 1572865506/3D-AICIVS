"""门面动态安全与封门件容量测试。"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from backend.solver_v2.api.adapter import InputAdapter
from backend.solver_v2.door.face_safety import (
    column_sf_at, door_seal_capacity, face_columns, is_door_seal_sku)
from backend.solver_v2.solver.unified_solver import UnifiedSolver


def _plc(sku, x, y, z, dx=0.56, dy=0.10, dz=0.388):
    return {"sku_id": sku, "x": x, "y": y, "z": z,
            "dx": dx, "dy": dy, "dz": dz, "weight_kg": 5.0}


class TestFaceColumns:
    def test_face_column_sf(self):
        placements = [_plc("D", 10.94, 0.0, i * 0.388) for i in range(6)]
        report = face_columns(placements, 12.032)
        assert report["face"] == pytest.approx(11.50, abs=1e-3)
        assert report["min_sf"] < 1.5
        assert report["unsafe_columns"] == 1

    def test_column_sf_reports_face_status(self):
        placements = [_plc("D", 10.94, 0.0, i * 0.388) for i in range(6)]
        cand = _plc("D", 10.94, 0.0, 6 * 0.388)
        info = column_sf_at(cand, placements)
        assert info["is_face"] is True
        assert info["sf"] < 1.5
        # 另一个已经更靠门的箱体 → 候选不再是门面
        behind = column_sf_at(cand, placements + [_plc("D", 11.4, 1.0, 0.0)])
        assert behind["is_face"] is False


class TestDoorSealCapacity:
    def test_4stop_capacity_is_infeasible(self):
        import json
        case = json.load(open(os.path.join(
            PROJECT_ROOT, "tests", "cases", "virtual",
            "virtual_multistop_4stop_40hq.json"), encoding="utf-8"))
        container = InputAdapter.parse_container(case["container"])
        cargo = InputAdapter.parse_cargo_list(case["cargo"])
        door = [c for c in cargo if is_door_seal_sku(c)]
        cap = door_seal_capacity(door, container, 0.698, min_sf=1.5)
        assert cap["feasible"] is False
        assert cap["required_depth_m"] > 0.698

    def test_intrinsic_stable_door_panel_fits(self):
        import json
        case = json.load(open(os.path.join(
            PROJECT_ROOT, "tests", "cases", "virtual",
            "virtual_3c_thin_door_40hq.json"), encoding="utf-8"))
        container = InputAdapter.parse_container(case["container"])
        cargo = InputAdapter.parse_cargo_list(case["cargo"])
        door = [c for c in cargo if is_door_seal_sku(c)]
        cap = door_seal_capacity(door, container, 4.0, min_sf=1.5)
        assert cap["feasible"] is True
        assert cap["per_sku"]


class TestDynamicTippingGate:
    def _solver(self):
        s = UnifiedSolver.__new__(UnifiedSolver)
        s.cL = 12.032
        s._door_step_depth = 0.25
        s._door_open_stability = False
        s._door_sku_ids = {"D"}
        s._current_rejection_counts = {}
        s._spatial_idx = None
        return s

    def test_tall_face_column_rejected(self):
        s = self._solver()
        placements = [_plc("D", 10.94, 0.0, i * 0.388) for i in range(6)]
        cand = _plc("D", 10.94, 0.0, 6 * 0.388)
        assert s._is_placement_tipping_safe(cand, placements) is False
        assert s._current_rejection_counts.get("DOOR_FACE_TIPPING", 0) == 1

    def test_candidate_behind_face_can_stack_tall(self):
        s = self._solver()
        placements = [_plc("D", 10.94, 0.0, i * 0.388) for i in range(6)]
        # 已有更靠门的箱体 → 候选在后面，不是实际门面
        placements.append(_plc("D", 11.4, 1.0, 0.0))
        cand = _plc("D", 10.94, 0.0, 6 * 0.388)
        assert s._is_placement_tipping_safe(cand, placements) is True
