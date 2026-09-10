"""审查回归：无效布局不得成功，未验证序列不得执行。"""
from backend.solver_v2.domain.models import (BoxDim, ContainerSpec, CargoSKU, QuantityPlan,
    Placement, Point3D, Orientation3D, PlacementContext)
from backend.solver_v2.solver.baseline_solver import SolverSolution, SolverTelemetry
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator
from backend.solver_v2.api.adapter import OutputAdapter
from backend.api.service import LoadingAPIService


def sample(overlap=False):
    c = ContainerSpec('TEST', BoxDim(3, 2, 2), 1000)
    sku = CargoSKU('A', '箱', BoxDim(1, 1, 1), 10, QuantityPlan(2))
    ps = [Placement(str(i), str(i), 'A', Point3D(0 if overlap else i, 0, 0),
          Orientation3D(1, 1, 1), 10, PlacementContext.MAIN_WALL) for i in range(2)]
    val = IndependentGlobalValidator.validate(c, ps, [sku])
    sol = SolverSolution(status='INVALID' if not val.is_valid else 'SUCCESS', container=c,
          placements=ps, validation_result=val, placed_count=2, unplaced_count=0,
          volume_utilization_pct=2/c.volume*100, total_weight_kg=20, telemetry=SolverTelemetry())
    return c, [sku], sol


def test_invalid_legacy_result():
    c, cargo, sol = sample(True)
    output = OutputAdapter.to_legacy_response(sol, c, cargo)
    assert output['success'] is False
    assert output['layout_status'] == 'INVALID'
    assert output['totalCollisions'] == 1


def test_missing_validation_is_not_success():
    c, cargo, sol = sample()
    sol.validation_result = None
    assert not OutputAdapter.to_legacy_response(sol, c, cargo)['success']


def test_invalid_job_not_executable():
    c, cargo, sol = sample(True)
    api = LoadingAPIService()
    result = api.register_solver_output('bad', sol, c, cargo)
    assert result['layout_status'] == 'INVALID'
    assert not result['executable']
    assert not result['sequence']['feasible']
    assert api.dispatch('/api/v1/loading/bad/export')[0] == 409


def test_sequence_reorders_support_before_upper():
    from backend.solver_v2.validation.sequence_check import check_sequence
    c,cargo,sol=sample()
    from dataclasses import replace
    sol.placements[1]=replace(sol.placements[1],position=Point3D(0,0,1))
    checked=check_sequence(c,cargo,list(reversed(sol.placements)))
    assert checked['status'] == 'FEASIBLE'
    assert checked['order'][0].position.z == 0


def test_sequence_timeout_never_means_feasible():
    from backend.solver_v2.validation.sequence_check import check_sequence
    c,cargo,sol=sample()
    assert check_sequence(c,cargo,sol.placements,budget_sec=0)['status'] == 'NOT_EVALUATED'
