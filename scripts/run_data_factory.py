# -*- coding: utf-8 -*-
"""
3D-AICIVS 数据工场自动化生产控制台 (Data Factory Automated Pipeline CLI)

一键驱动 10,000 级多样化工况合成、高质量求解、防蜂窝空洞过滤与金牌方案沉淀。

使用示例:
  # 1. 快速合成并归档 20 组金牌方案
  python scripts/run_data_factory.py --generate 20 --output-dir data/factory_preview

  # 2. 大规模批生产 500 组真实工业工况
  python scripts/run_data_factory.py --generate 500 --output-dir data/golden_solutions
"""
from __future__ import annotations

import os
import sys
import time
import argparse
from typing import List

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.solver_v2.data_pipeline import (
    ManifestSynthesizer,
    AntiCavityFilter,
    SolutionCollector,
    PackingDataset,
)
from backend.solver_v2.solver.unified_solver import UnifiedSolver


def run_factory_pipeline(
    count: int = 10,
    output_dir: str = "data/golden_solutions",
    seed: int = 42,
):
    print("=" * 80)
    print(f"🏭 3D-AICIVS 数据工场流水线启动 | 目标工况数: {count} | 输出目录: {output_dir}")
    print("=" * 80)

    synthesizer = ManifestSynthesizer(seed=seed)
    quality_filter = AntiCavityFilter()
    collector = SolutionCollector(output_dir=output_dir, quality_filter=quality_filter)

    gold_count = 0
    silver_count = 0
    reject_count = 0

    t_start = time.time()

    for idx in range(count):
        scenario_id = f"fact_{seed}_{idx+1:05d}"
        container, skus = synthesizer.generate_scenario(scenario_id=scenario_id)

        solver = UnifiedSolver(container)
        t0 = time.perf_counter()
        solution = solver.solve(skus, time_budget=5.0, seed=seed + idx)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        report = collector.process_and_archive(
            scenario_id=scenario_id,
            container=container,
            cargo_skus=skus,
            placements=solution.placements,
            execution_time_ms=elapsed_ms,
        )

        if report.rating == "GOLD":
            gold_count += 1
            icon = "🥇 [GOLD]"
        elif report.rating == "SILVER":
            silver_count += 1
            icon = "🥈 [SILVER]"
        else:
            reject_count += 1
            icon = "❌ [REJECT]"

        # 简洁打印，遵循 AGENTS.MD 单行日志规范
        print(f"[{idx+1:03d}/{count:03d}] {scenario_id} {icon} | 容积率: {report.volume_utilization_pct:.1f}% | 刚性率: {report.rigid_fulfillment_pct:.1f}% | 空洞率: {report.enclosed_cavity_ratio_pct:.1f}% | 耗时: {elapsed_ms:.0f}ms")

    elapsed_total = time.time() - t_start

    print("=" * 80)
    print(f"🎉 数据工场处理完毕! 耗时: {elapsed_total:.1f}s")
    print(f"   🥇 金牌示范方案: {gold_count} ({gold_count/count*100:.1f}%)")
    print(f"   🥈 银牌合格方案: {silver_count} ({silver_count/count*100:.1f}%)")
    print(f"   ❌ 质量淘汰方案: {reject_count} ({reject_count/count*100:.1f}%)")
    print(f"   📁 沉淀数据集索引: {os.path.join(output_dir, 'dataset_index.jsonl')}")
    print("=" * 80)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="3D-AICIVS Data Factory Pipeline CLI")
    parser.add_argument("--generate", type=int, default=5, help="生成与求解的工况数量")
    parser.add_argument("--output-dir", type=str, default="data/golden_solutions", help="金牌方案沉淀目录")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")

    args = parser.parse_args()
    run_factory_pipeline(count=args.generate, output_dir=args.output_dir, seed=args.seed)
