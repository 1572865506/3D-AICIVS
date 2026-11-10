# _archive — 非生产路径归档区

本目录收录**不参与生产链路**的求解器与实验模块（AGENTS.md 5.7「唯一生产路径」）。
归档原则：移动而非删除，保留可追溯性；禁止在 server/API 请求路径引用。

| 归档内容 | 原路径 | 归档原因 |
|:---|:---|:---|
| `search/`（9 模块） | `backend/solver_v2/search/` | 实验性分层墙搜索，生产用 UnifiedSolver；约束覆盖不一致 |
| `physics_kernel/`（7 模块） | `backend/solver_v2/physics_kernel/` | 仅 guided 引擎引用；生产门禁为 unified_solver 内置 |
| `placement_engine/` | `backend/solver_v2/placement_engine/` | GuidedBeamSearch 实验引擎（依赖未训练 Transformer） |
| `cpsat_hybrid_solver.py` / `cpsat_engine.py` | `solver/` | CP-SAT 混合求解，未接入 API |
| `lns_optimizer.py` / `constructive_placer.py` | `solver/` | 旧 LNS/构造放置；生产 LNS 已内置于 UnifiedSolver |
| `elastic_recovery.py` / `swap_optimizer.py` / `gap_filler.py` | `solver/` | 孤岛优化器（生产回填/压缩已内联） |

对应测试已移至 `tests/_archive/`（由 `tests/conftest.py` 排除收集）。

恢复方式：把文件移回原路径并修正 `backend/solver_v2/__init__.py` / `solver/__init__.py`
的导出；**不要**在生产请求路径直接引用。
