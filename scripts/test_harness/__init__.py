"""
3D-AICIVS 可扩展测试平台 (Test Harness)

用途：批量生成、执行、归因、报告测试用例，覆盖 300+ 生产级装载工况。
组件：
  - case_generator: 固定用例生成 + 受控随机化 + 对抗性变异
  - runner: 测试执行引擎（超时保护、标签过滤、增量运行）
  - analyzer: 故障归因聚类引擎（自动分类 + 根因推断）
  - reporter: 结构化报告生成（Markdown 摘要 + JSON 数据）
"""

__version__ = "1.0.0"
