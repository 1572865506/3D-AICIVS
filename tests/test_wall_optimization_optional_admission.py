from types import SimpleNamespace
import unittest

from backend.solver_v2.domain.models import BoxDim,ContainerSpec
from src.solver.integration.wall.WallOptimizationAdapter import WallOptimizationAdapter


class _FailedEngine:
    def __init__(self,result):
        self.result=result

    def optimize(self,*_args):
        return self.result


def _fixtures():
    result=SimpleNamespace(
        status="FAILED",
        transition_walls=(),
        chain=SimpleNamespace(valid=False),
        optimized_wall_end_x=7.2,
    )
    container=ContainerSpec("TEST",BoxDim(12.0,2.35,2.69),1000.0)
    wall_prepared=SimpleNamespace(
        plan=object(),solver_cargo=(),original_container=container,
    )
    door_prepared=SimpleNamespace(
        door_wall=SimpleNamespace(placements=(SimpleNamespace(x=10.8),)),
    )
    return result,wall_prepared,door_prepared


class TestWallOptimizationOptionalAdmission(unittest.TestCase):
    def test_optional_admission_falls_back_with_explicit_diagnostics(self):
        result,wall_prepared,door_prepared=_fixtures()
        adapter=WallOptimizationAdapter(_FailedEngine(result))

        self.assertIsNone(adapter.try_prepare(wall_prepared,door_prepared))
        self.assertIs(adapter.last_result,result)
        diagnostic=dict(adapter.last_diagnostic)
        self.assertAlmostEqual(diagnostic.pop("remaining_transition_gap_m"),3.6)
        self.assertEqual(diagnostic,{
            "attempted":True,
            "status":"FAILED",
            "admitted":False,
            "admission_mode":"CARGO_WALL_FORMATION_FALLBACK",
            "fallback":"CARGO_WALL_FORMATION",
            "reasons":["NO_TRANSITION_WALL","WALL_CHAIN_INVALID","TRANSITION_GAP_EXCEEDS_LIMIT"],
            "transition_wall_count":0,
            "wall_chain_valid":False,
            "door_back_anchor_ready":False,
            "door_back_anchor_coverage":0.0,
            "optimized_wall_end_x":7.2,
            "door_anchor_x":10.8,
        })

    def test_strict_entry_point_still_rejects_failed_optimization(self):
        result,wall_prepared,door_prepared=_fixtures()
        adapter=WallOptimizationAdapter(_FailedEngine(result))

        with self.assertRaisesRegex(ValueError,"WALL_OPTIMIZATION_FAILED"):
            adapter.prepare(wall_prepared,door_prepared)


if __name__=="__main__":unittest.main()
