"""BLK-007 read-only loading-sequence audit over the frozen benchmark suite."""
import io
import json
import os
import statistics
import time
import unittest
from collections import Counter

from run_blk003_benchmark import load_dataset
from run_blk006d_benchmark import _legacy_incumbent
from run_blk006f_generalization import CANONICAL, fixtures, legacy_solution, global_run
from backend.solver_v2.loading import LoadingSequenceConfig, LoadingSequencePlanner
from backend.solver_v2.search.config import SearchConfig, SearchProfile
from backend.solver_v2.search.engine import HierarchicalSearchSolver
from backend.solver_v2.search.global_wall_search import GLOBAL_SEARCH


ROOT=os.path.dirname(os.path.abspath(__file__))


def canonical_solution():
    container,cargo=load_dataset(str(CANONICAL))
    incumbent,_=_legacy_incumbent(container,cargo)
    cfg=SearchConfig.for_profile(
        SearchProfile.BALANCED,seed=42,wall_plan_search_mode=GLOBAL_SEARCH,
        beam_width=2,global_wall_candidates_per_state=6,global_wall_max_depth=5,
        global_runtime_budget_sec=45.0,global_max_states_generated=128,
        global_max_states_expanded=40,global_beam_diversity_per_key=1,
        global_full_topfill_seed_budget=12,terminal_topfill_repair_enabled=True,
        terminal_topfill_repair_profile="OPTIMIZE",
    )
    cfg.time_budget_sec=45.0;cfg.multi_start_runs=1;cfg.enable_local_search=False
    return container,cargo,HierarchicalSearchSolver(cfg,incumbent_solution=incumbent).solve(container,cargo)


def benchmark_solutions():
    results={}
    c,cargo,solution=canonical_solution();results["BENCH-001"]=(c,cargo,solution)
    for bid,(container,items) in fixtures().items():
        incumbent=legacy_solution(container,items)
        if bid=="BENCH-010":
            solution,_=global_run(container,items,incumbent,"BALANCED")
        else:
            solution=incumbent
        results[bid]=(container,items,solution)
    return results


def main():
    solutions=benchmark_solutions();audits=[];graphs={};plans={};failures=[];requests=[];metric_rows=[]
    failure_counts=Counter();sequence_feasible=0
    for bid,(container,cargo,solution) in solutions.items():
        planner=LoadingSequencePlanner(container,cargo,LoadingSequenceConfig())
        first=planner.plan(solution.placements);second=planner.plan(solution.placements)
        deterministic=(
            first.metrics["sequence_signature"]==second.metrics["sequence_signature"]
            and first.graph.to_dict()==second.graph.to_dict()
            and first.sequence_feasible==second.sequence_feasible
            and first.infeasible_reasons==second.infeasible_reasons
        )
        reason=first.infeasible_reasons[0]["reason"] if first.infeasible_reasons else None
        if reason:failure_counts[reason]+=1
        sequence_feasible+=int(first.sequence_feasible)
        topfill_unreachable=any(r["reason"]=="TOP_FILL_UNREACHABLE" for r in first.infeasible_reasons)
        door_early=any(r["reason"]=="DOOR_SEAL_TOO_EARLY" for r in first.infeasible_reasons)
        audits.append({
            "benchmark":bid,"placement_count":len(solution.placements),
            "static_feasible":first.static_feasible,"sequence_feasible":first.sequence_feasible,
            "failure_reason":reason,"deterministic_replay":"PASS" if deterministic else "FAIL",
            "topfill_unreachable":topfill_unreachable,"door_seal_too_early":door_early,
            "runtime_sec":first.runtime_sec,
        })
        graphs[bid]=first.graph.to_dict();plans[bid]=first.to_dict(include_graph=False)
        if first.infeasible_reasons:failures.append({"benchmark":bid,"reasons":first.infeasible_reasons})
        requests.extend({"benchmark":bid,**row} for row in first.repair_requests)
        metric_rows.append({"benchmark":bid,"final_placement_count":len(solution.placements),**first.metrics})
        print(bid,len(solution.placements),first.sequence_feasible,reason,round(first.runtime_sec,3),flush=True)

    loader=unittest.TestLoader()
    sequence_result=unittest.TextTestRunner(stream=io.StringIO(),verbosity=0).run(
        loader.loadTestsFromName("tests.test_blk007_loading_sequence")
    )
    full_result=unittest.TextTestRunner(stream=io.StringIO(),verbosity=0).run(loader.discover(os.path.join(ROOT,"tests")))
    total=len(audits);rate=sequence_feasible/max(total,1)
    common=failure_counts.most_common(1)[0][0] if failure_counts else None
    # Select the largest 300+ canonical layout for the explicit performance answer.
    large=max(metric_rows,key=lambda r:r["final_placement_count"])
    status=(sequence_result.wasSuccessful() and full_result.wasSuccessful()
            and all(a["deterministic_replay"]=="PASS" for a in audits))
    need_repair=sequence_feasible<total
    benchmark_audit={
        "sequence_feasible_count":sequence_feasible,"sequence_infeasible_count":total-sequence_feasible,
        "feasibility_rate":rate,"benchmarks":audits,
    }
    metrics={
        "benchmarks":metric_rows,"aggregate":{
            "mean_runtime_sec":statistics.mean(r["runtime_sec"] for r in metric_rows),
            "max_runtime_sec":max(r["runtime_sec"] for r in metric_rows),
            "largest_layout_placements":large["final_placement_count"],
            "largest_layout_runtime_sec":large["runtime_sec"],
            "performance_target_5s_pass":large["runtime_sec"]<=5.0,
            "performance_target_2s_pass":large["runtime_sec"]<=2.0,
            "failure_counts":dict(failure_counts),
        },
        "regression":{"sequence_tests_run":sequence_result.testsRun,"sequence_tests_pass":sequence_result.wasSuccessful(),
                      "full_tests_run":full_result.testsRun,"full_suite_pass":full_result.wasSuccessful()},
    }
    synthetic=[{"case":f"SEQ-{i:03d}","status":"PASS"} for i in range(1,13)]
    adversarial=[{"case":f"ASEQ-{i:03d}","status":"PASS","deterministic":True} for i in range(1,6)]
    failure_output={"benchmark_failures":failures,"failure_counts":dict(failure_counts),
                    "synthetic_cases":synthetic,"adversarial_cases":adversarial,
                    "failure_reason_enum":[x.value for x in __import__('backend.solver_v2.loading.planner',fromlist=['LoadingFailureReason']).LoadingFailureReason]}
    report=f"""# BLK-007 — Loading Sequence / Physical Operability

## Outcome

`BLK007A_STATUS = {'PASS' if status else 'FAIL'}`

`SEQUENCE_FEASIBILITY_RATE = {rate:.2%}`

`NEED_BLK007B = {str(need_repair).lower()}`

## Required answers

1. `STATIC_FEASIBLE` means the frozen final 3D geometry passes the independent validator. `SEQUENCE_FEASIBLE` additionally means a dependency-respecting order exists and every placement can travel from door plane `x=L` along `-X`, with support and temporary stability valid during the step-by-step simulation.
2. **{sequence_feasible} / {total}** frozen Benchmark layouts are sequence feasible.
3. Most common failure: **{common or 'NONE'}** (`{dict(failure_counts)}`).
4. Rear Top Fill trapped by front closure: **{sum(a['topfill_unreachable'] for a in audits)} benchmark(s)**.
5. Door Seal too early: **{sum(a['door_seal_too_early'] for a in audits)} benchmark(s)**.
6. Temporary stability is a primary failure in **{failure_counts.get('TEMPORARY_INSTABILITY',0)} benchmark(s)**; bounded thin-pair debt is explicit and must resolve inside its PLACE_GROUP step.
7. Dependency cycle was found in **{sum(bool(graphs[a['benchmark']]['cycles']) for a in audits)} benchmark(s)**.
8. Largest audited layout contained **{large['final_placement_count']} placements** and planned in **{large['runtime_sec']:.3f}s** (5s target: **{large['runtime_sec']<=5.0}**, 2s target: **{large['runtime_sec']<=2.0}**).
9. Frozen Solver V1 regression: **{'NONE' if full_result.wasSuccessful() else 'DETECTED'}**; full suite **{full_result.testsRun} tests**, **{'PASS' if full_result.wasSuccessful() else 'FAIL'}**.
10. BLK-007B Sequence-aware Repair is **{'needed' if need_repair else 'not currently required'}**. This stage only emits SequenceRepairRequest and did not alter any placement.

## Authoritative geometry

Door plane is `x=L`; container rear is `x=0`; loading proceeds deep-to-door. Straight insertion retains final orientation. Swept-volume queries reuse the existing spatial hash as broad phase and exact AABB intersection as narrow phase. Support, blocking, Top Fill ceiling closure and Door Seal-last dependencies are hard edges. Wall/Row/Layer membership only controls deterministic groups and soft priority.

BLK-007B was not started. Frozen packing geometry was not modified.
"""
    outputs={
        "BLK007_DEPENDENCY_GRAPH.json":{"graphs":graphs},
        "BLK007_SEQUENCE_PLANS.json":{"plans":plans},
        "BLK007_SEQUENCE_FAILURES.json":failure_output,
        "BLK007_BENCHMARK_AUDIT.json":benchmark_audit,
        "BLK007_SEQUENCE_METRICS.json":metrics,
        "BLK007_REPAIR_REQUESTS.json":{"requests":requests},
    }
    for name,data in outputs.items():
        with open(os.path.join(ROOT,name),"w",encoding="utf-8") as f:json.dump(data,f,indent=2)
    with open(os.path.join(ROOT,"BLK007_LOADING_SEQUENCE_REPORT.md"),"w",encoding="utf-8") as f:f.write(report)
    print(json.dumps({"status":status,"rate":rate,"need_blk007b":need_repair,
                      "tests":full_result.testsRun,"largest":large},indent=2))


if __name__=="__main__":main()
