# -*- coding: utf-8 -*-
"""
Transformer 决策大脑 (Transformer Strategy Brain)

基于 Transformer/Attention 机制的装载策略决策模块。
通过 Self-Attention 理解货物间关系，通过 Cross-Attention 匹配货物与空间。
输出最优装载顺序，由 placement_engine 执行。

被谁调用:
  - __init__.py solve() 入口
"""
