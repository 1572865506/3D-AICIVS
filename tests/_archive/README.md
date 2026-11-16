# tests/_archive — 失效测试归档区

本目录收录**无法收集/依赖已归档模块**的历史测试，由 `tests/conftest.py` 排除收集。
归档原则：移动而非删除，保留可追溯性；不进入 CI/回归门禁。

| 归档内容 | 依赖的已移除模块 | 归档原因 |
|:---|:---|:---|
| `test_blk004b` / `test_blk005b` / `test_blk007e*` / `test_blk007f*` / `test_blk008a`（16 项） | `run_blk003_benchmark`（根目录脚本，清洗时移除） | 数据集加载器缺失，测试无法收集 |
| `test_blk006a~f` / `test_p0_blk001_anchors`（5 项） | `backend.solver_v2.search/`（已归档，见 `backend/solver_v2/_archive/README.md`） | 搜索子系统归档，生产路径为 UnifiedSolver |
| 其余早期测试 | physics_kernel / placement_engine 等 | 同上 |

对应被测模块仍保留在 `backend/solver_v2/_archive/`。若需恢复某项行为，
优先在 `tests/` 下按**唯一生产路径**（UnifiedSolver + 统一门禁）重写，而不是回移依赖。
