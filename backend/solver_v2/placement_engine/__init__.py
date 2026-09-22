# -*- coding: utf-8 -*-
"""
干净放置引擎 (Clean Placement Engine)

无条件分支的顺序放置器。按给定的货物序列逐件放置，
每一步仅通过共享物理内核做可行性判定。
不含任何货物类型特判 (if is_slender 等)。

被谁调用:
  - brain/inference.py (执行 Transformer 输出的放置序列)
  - data_pipeline/solution_recorder.py (录制训练数据)
  - __init__.py solve() 入口
"""
