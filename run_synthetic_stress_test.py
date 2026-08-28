"""
CLI Runner for Synthetic Cargo Stress Benchmark & Diagnostics.
"""
import argparse
import json
import sys

from src.unified_pipeline.benchmark.SyntheticStressBenchmark import (
    SyntheticCargoStressBenchmark,
    GeneratorRangeConfig
)


def main():
    parser = argparse.ArgumentParser(description="Run Monte-Carlo Synthetic Cargo Stress Benchmark")
    parser.add_argument("--count", type=int, default=20, help="Number of randomized scenarios to test")
    parser.add_argument("--seed", type=int, default=100, help="Random seed start")
    args = parser.parse_args()

    benchmark = SyntheticCargoStressBenchmark()
    print(f"\n================================================================================")
    print(f"       3D-AICIVS SYNTHETIC CARGO MONTE-CARLO STRESS BENCHMARK (N={args.count})")
    print(f"================================================================================")
    print(f"Parametric Range: SKU [5-25], Dims [0.3-1.2m], Wt [2-35kg], Qty [5-250]")
    print(f"Containers:       20GP / 40GP / 40HQ randomized testing")
    print(f"Running automated stress suite...\n")

    report = benchmark.run_stress_suite(num_scenarios=args.count, seed_start=args.seed)

    print(f"--------------------------------------------------------------------------------")
    print(f"                            BENCHMARK SUMMARY REPORT")
    print(f"--------------------------------------------------------------------------------")
    print(f"  - Total Scenarios Tested:        {report['total_scenarios_tested']}")
    print(f"  - 100% Zero-Defect Pass Rate:    {report['overall_pass_rate_pct']}%")
    print(f"  - Average Volume Utilization:    {report['average_volume_utilization_pct']}%")
    print(f"  - Average Zone Compliance:       {report['average_zone_compliance_pct']}%")
    print(f"  - Average Solving Runtime:       {report['average_runtime_ms']} ms")
    print(f"  - Total Benchmark Execution:     {report['total_benchmark_time_sec']} s")
    print(f"--------------------------------------------------------------------------------")

    # Display scenarios overview table
    print(f"\n{'ID':<14} {'Type':<6} {'SKUs':<6} {'Total Boxes':<12} {'Placed':<8} {'Util %':<8} {'Zone %':<8} {'Physics':<8} {'Runtime'}")
    print(f"-" * 80)
    for r in report['detailed_results']:
        phy_str = "VALID" if r['is_physically_valid'] else "FAILED"
        print(f"{r['scenario_id']:<14} {r['container_type']:<6} {r['total_skus']:<6} {r['total_manifest_boxes']:<12} {r['total_placed_boxes']:<8} {r['volume_utilization_pct']:<8.1f} {r['zone_compliance_pct']:<8.1f} {phy_str:<8} {r['runtime_ms']:.1f}ms")

    # Issue points analysis
    print(f"\n================================================================================")
    print(f"                     DIAGNOSED ISSUE POINTS & BOTTLENECKS")
    print(f"================================================================================")
    issues = report['identified_issue_points']
    if not issues:
        print("  [OK] Zero issues detected! All scenarios satisfied 100% physics, planarity, and zone rules.")
    else:
        print(f"  Found {len(issues)} diagnostic alerts:")
        for idx, iss in enumerate(issues, 1):
            print(f"  [{idx:02d}] {iss['scenario']} ({iss['container']}): {iss['issue']}")
    print(f"================================================================================\n")


if __name__ == '__main__':
    main()
