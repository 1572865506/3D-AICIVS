"""多层载荷守恒与放置前拒绝的真实回归。"""
from backend.solver_v2.domain.models import (BoxDim, ContainerSpec, CargoSKU, QuantityPlan,
    StackingPolicy, Placement, Point3D, Orientation3D, PlacementContext)
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator as V
from backend.solver_v2.solver.unified_solver import UnifiedSolver
from backend.solver_v2.stability.load_ledger import LoadLedger


def cargo():
    return CargoSKU('A', '箱', BoxDim(1, 1, 1), 10, QuantityPlan(3),
                    stacking_policy=StackingPolicy(max_bearing_kg=15))


def test_validator_rejects_three_layers():
    c = ContainerSpec('TEST', BoxDim(1.1, 1.1, 3.1), 1000)
    ps = [Placement(str(i), str(i), 'A', Point3D(0,0,i), Orientation3D(1,1,1),
                    10, PlacementContext.MAIN_WALL) for i in range(3)]
    v = V.validate(c, ps, [cargo()])
    assert not v.is_valid
    assert any(x.violation_type.value == 'BEARING_EXCEEDED' for x in v.violations)


def test_solver_rejects_third_box_before_placement():
    c = ContainerSpec('TEST', BoxDim(1.1, 1.1, 3.1), 1000)
    result = UnifiedSolver(c).solve([cargo()], mode='FAST')
    assert result.validation_result.is_valid
    assert result.placed_count == 2


def test_split_load_is_conserved_with_partial_contact():
    ledger = LoadLedger()
    left = dict(x=0,y=0,z=0,dx=.4,dy=1,dz=1,weight_kg=1,sku_id='L')
    right = dict(x=.6,y=0,z=0,dx=.4,dy=1,dz=1,weight_kg=1,sku_id='R')
    upper = dict(x=0,y=0,z=1,dx=1,dy=1,dz=1,weight_kg=10,sku_id='U')
    ledger.rebuild([left,right])
    ledger.commit(upper,[left,right])
    assert ledger.loads[id(left)] == 5
    assert ledger.loads[id(right)] == 5
    ledger.rebuild([left,right])
    assert sum(ledger.loads.values()) == 0
