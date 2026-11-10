"""pytest 配置：归档的历史测试不参与收集（其依赖模块已移入 backend/solver_v2/_archive/）。"""
collect_ignore_glob = ["_archive/*", "_archive/**/*"]
