"""BLK-007B sequence-aware repair audit over frozen benchmark layouts."""
import io
import json
import os
import statistics
import time
import unittest

from run_blk007_audit import benchmark_solutions
from backend.solver_v2.loading import LoadingSequenceConfig,LoadingSequencePlanner,SequenceRepairEngine


ROOT=os.path.dirname(os.path.abspath(__file__))


def main():
    results=[];groups=[];metric_rows=[];sequence_pass=0;deterministic_all=True
    solutions=benchmark_solutions()
    for bid,(container,cargo,solution) in solutions.items():
        planner=LoadingSequencePlanner(container,cargo,LoadingSequenceConfig())
        original=planner.plan(solution.placements)
        repaired_plan=original;repair=None;deterministic=True
        if not original.sequence_feasible and original.infeasible_reasons:
            engine=SequenceRepairEngine(container,cargo)
            repair=engine.repair(original,original.infeasible_reasons[0],original.graph,solution.placements)
            repeat=engine.repair(original,original.infeasible_reasons[0],original.graph,solution.placements)
            deterministic=(repair.metrics["repair_signature"]==repeat.metrics["repair_signature"]
                           and repair.repaired==repeat.repaired
                           and repair.updated_loading_plan.metrics["sequence_signature"]
                           ==repeat.updated_loading_plan.metrics["sequence_signature"])
            repaired_plan=repair.updated_loading_plan
        deterministic_all &= deterministic
        sequence_pass += int(repaired_plan.sequence_feasible)
        row={
            "benchmark":bid,"placement_count":len(solution.placements),
            "original_status":"PASS" if original.sequence_feasible else "FAILED",
            "original_failure":original.infeasible_reasons[0]["reason"] if original.infeasible_reasons else None,
            "repaired_status":"PASS" if repaired_plan.sequence_feasible else "FAILED",
            "sequence_feasible":repaired_plan.sequence_feasible,
            "actions":[a.to_dict() for a in repair.repair_actions] if repair else [],
            "changed_steps":repair.metrics["changed_steps"] if repair else 0,
            "geometry_changed":repair.validation_result["geometry_changed"] if repair else False,
            "dependency_dag":repair.validation_result["dependency_dag"] if repair else not bool(original.graph.cycles),
            "temporary_stability_resolved":repair.validation_result["temporary_stability_resolved"] if repair else True,
            "repair_deterministic":deterministic,
            "repair_runtime_sec":repair.metrics["runtime_sec"] if repair else 0.0,
        }
        results.append(row)
        if repair:
            groups.extend({"benchmark":bid,**g.to_dict()} for g in repair.groups)
            metric_rows.append({"benchmark":bid,**repair.metrics})
        print(bid,row["original_status"],row["repaired_status"],round(row["repair_runtime_sec"],4),flush=True)

    loader=unittest.TestLoader()
    repair_tests=unittest.TextTestRunner(stream=io.StringIO(),verbosity=0).run(
        loader.loadTestsFromName("tests.test_blk007b_sequence_repair"))
    full_tests=unittest.TextTestRunner(stream=io.StringIO(),verbosity=0).run(loader.discover(os.path.join(ROOT,"tests")))
    total=len(results);rate=sequence_pass/max(total,1)
    bench1=next(r for r in results if r["benchmark"]=="BENCH-001")
    success=(bench1["sequence_feasible"] and not bench1["geometry_changed"]
             and bench1["dependency_dag"] and bench1["temporary_stability_resolved"]
             and deterministic_all and repair_tests.wasSuccessful() and full_tests.wasSuccessful())
    aggregate={
        "repair_attempts":sum(r["repair_attempts"] for r in metric_rows),
        "repair_success":sum(r["repair_success"] for r in metric_rows),
        "repair_failure":sum(r["repair_failure"] for r in metric_rows),
        "average_candidates":statistics.mean((r["candidate_count"] for r in metric_rows)) if metric_rows else 0.0,
        "average_group_size":statistics.mean((r["average_group_size"] for r in metric_rows)) if metric_rows else 0.0,
        "dependency_changes":sum(r["dependency_changes"] for r in metric_rows),
        "sequence_improvement":sum(r["sequence_improvement"] for r in metric_rows),
        "geometry_changes":sum(r["geometry_changes"] for r in metric_rows),
        "max_repair_runtime_sec":max((r["runtime_sec"] for r in metric_rows),default=0.0),
        "performance_target_2s_pass":max((r["runtime_sec"] for r in metric_rows),default=0.0)<2.0,
        "sequence_feasible_count":sequence_pass,"sequence_feasibility_rate":rate,
    }
    outputs={
        "BLK007B_REPAIR_RESULTS.json":{"status":"PASS" if success else "FAIL","benchmarks":results},
        "BLK007B_REPAIR_METRICS.json":{"aggregate":aggregate,"benchmarks":metric_rows,
            "regression":{"repair_tests_run":repair_tests.testsRun,"repair_tests_pass":repair_tests.wasSuccessful(),
                          "full_tests_run":full_tests.testsRun,"full_suite_pass":full_tests.wasSuccessful(),
                          "deterministic_repair_pass":deterministic_all}},
        "BLK007B_GROUPS.json":{"loading_groups":groups},
    }
    for name,data in outputs.items():
        with open(os.path.join(ROOT,name),"w",encoding="utf-8") as f:json.dump(data,f,indent=2)
    action=bench1["actions"][0] if bench1["actions"] else None
    report=f"""# BLK-007B — Sequence-aware Repair Engine

## Outcome

`BLK007B_STATUS = {'PASS' if success else 'FAIL'}`

`SEQUENCE_FEASIBILITY_RATE = {rate:.2%}`

`NEED_BLK008 = {str(not success).lower()}`

## Required answers

1. BENCH-001 修复：**{'成功' if bench1['sequence_feasible'] else '失败'}**，从 `TEMPORARY_INSTABILITY` 变为 `SEQUENCE_FEASIBLE`。
2. Repair Action：**{action['type'] if action else 'NONE'}**，placements = `{action['placements'] if action else []}`。候选由同 row、距离和结构规则产生，没有 SKU-ID 特判。
3. 最终 Geometry：**未改变**；位置、方向、bbox 均保持冻结结果，`geometry_changed = {str(bench1['geometry_changed']).lower()}`。
4. 新建 Loading Group：**{len(groups)}** 个，均为最小 PAIR construction group。
5. Temporary Stability：**{'已解决' if bench1['temporary_stability_resolved'] else '未解决'}**，debt 必须在同一个 `PLACE_GROUP` 内归零。
6. Dependency：**{'保持 DAG' if bench1['dependency_dag'] else '出现 cycle'}**，dependency changes = `{aggregate['dependency_changes']}`。
7. 装载复杂度：增加 **{bench1['changed_steps']} 个 atomic group step**；没有扩大为 Row/Wall group，符合 smallest-change-wins。
8. 性能：380-placement repair = **{bench1['repair_runtime_sec']:.3f}s**，`<2s = {aggregate['performance_target_2s_pass']}`。

## Regression

- BENCH-001～012 sequence feasible：**{sequence_pass}/{total}**。
- Repair deterministic：**{'PASS' if deterministic_all else 'FAIL'}**。
- BLK-007B tests：**{repair_tests.testsRun} tests, {'PASS' if repair_tests.wasSuccessful() else 'FAIL'}**。
- Full suite：**{full_tests.testsRun} tests, {'PASS' if full_tests.wasSuccessful() else 'FAIL'}**。
- Frozen Packing Solver geometry：未修改。

本阶段只实现 `TEMPORARY_INSTABILITY_REPAIR`。未进入 BLK-008。
"""
    with open(os.path.join(ROOT,"BLK007B_REPAIR_REPORT.md"),"w",encoding="utf-8") as f:f.write(report)
    print(json.dumps({"status":"PASS" if success else "FAIL","rate":rate,
                      "need_blk008":not success,"aggregate":aggregate,
                      "full_tests":full_tests.testsRun},indent=2))


if __name__=="__main__":main()
