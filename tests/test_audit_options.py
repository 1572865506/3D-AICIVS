"""统一入口及微小预算必须及时结束；不返回未验证试算。"""
import time
import pytest
from backend.solver_v2 import solve
from backend.solver_v2.solver.unified_solver import UnifiedSolver
from backend.solver_v2.solver.options import SolverOptions
from tests.test_audit_bearing import cargo
from backend.solver_v2.domain.models import ContainerSpec, BoxDim


def test_options_reach_solver(monkeypatch):
    observed=[]
    def trial(self, cargos, config):
        observed.append(config['name']);return [],{}
    monkeypatch.setattr(UnifiedSolver,'_solve_single_trial',trial)
    solve(ContainerSpec('TEST',BoxDim(2,2,3),1000),[cargo()],mode='FAST',time_budget=1)
    assert len(observed)==2


@pytest.mark.parametrize('options',[{'time_budget':0},{'time_budget':float('nan')},{'mode':'bad'},{'typo':1}])
def test_bad_options_rejected(options):
    with pytest.raises(ValueError):SolverOptions.parse(options)


def test_tiny_budget_does_not_publish_trial():
    c=ContainerSpec('TEST',BoxDim(12,2.3,2.7),1000)
    start=time.monotonic()
    result=solve(c,[cargo()],time_budget=1e-9)
    assert time.monotonic()-start < 1
    assert result.status=='TIMED_OUT'
    assert result.placed_count==0
    assert result.validation_result.is_valid
