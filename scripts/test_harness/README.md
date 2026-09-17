# 3D-AICIVS 可扩展测试平台 (Test Harness)

## 快速开始

```bash
# 1. 生成 Phase 1 固定用例（44 个，补到 ~100 总用例）
python scripts/test_harness/case_generator.py --mode fixed

# 2. 执行 Tier 1 核心测试（~100 用例，约 10 分钟）
python scripts/test_harness/runner.py --tier 1

# 3. 故障归因分析
python scripts/test_harness/analyzer.py

# 4. 生成报告
python scripts/test_harness/reporter.py
```

## 组件说明

| 组件 | 文件 | 用途 |
|:---|:---|:---|
| 用例生成器 | `case_generator.py` | 固定模板 / 受控随机 / 对抗变异 |
| 执行引擎 | `runner.py` | 发现 → 过滤 → 执行 → 超时保护 |
| 归因引擎 | `analyzer.py` | 15 种故障分类 → 聚类 → 修复建议 |
| 报告生成器 | `reporter.py` | Markdown 摘要 + JSON 数据 |

## 用例生成

### 固定模板生成
```bash
python scripts/test_harness/case_generator.py --mode fixed
python scripts/test_harness/case_generator.py --mode fixed --dry-run  # 演练
```

### 受控随机生成
```bash
python scripts/test_harness/case_generator.py --mode random --count 50 --seed 42
python scripts/test_harness/case_generator.py --mode random --count 100 --seed 123
```

### 对抗性变异
```bash
python scripts/test_harness/case_generator.py --mode mutate --source tests/cases/case_15_all_constraints.json --count 5
```

## 测试执行

### 分层执行
```bash
python scripts/test_harness/runner.py --tier 1     # 核心 100 用例 (~10min)
python scripts/test_harness/runner.py --tier 2     # 全部用例 (~30min)
python scripts/test_harness/runner.py --all        # 等同 tier 2
```

### 标签过滤
```bash
python scripts/test_harness/runner.py --tags door,bearing     # 门区 + 承重相关
python scripts/test_harness/runner.py --container 20GP,45HQ   # 特定柜型
python scripts/test_harness/runner.py --ids 14-SKU-1845       # 指定用例
```

### 增量运行
```bash
python scripts/test_harness/runner.py --incremental  # 跳过未修改的用例
```

## 报告目录结构

```
tests/harness_reports/
├── latest_results.json       # 最新执行结果
├── latest_analysis.json      # 最新归因分析
├── latest_report.md          # Agent 可消费的 Markdown 摘要
├── latest_report.json        # 合并报告
├── .case_hashes.json         # 增量运行哈希缓存
└── history/                  # 历史快照（趋势追踪）
    ├── run_20260917_160000.json
    └── ...
```

## 与 AGENTS.md 的关系

- **L1-L3 测试流程不变**：测试平台作为 L4 级存在
- **日常开发**：仍使用 L1 (import check) + L2 (batch_sku_diagnostic)
- **提交前**：运行测试平台 Tier 1 或 Tier 2
- **重大重构**：Tier 3（全量 + 新随机用例）
