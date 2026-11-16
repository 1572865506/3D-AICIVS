"""请求参数上限、清单规模校验与全局 solve 并发闸门。

为什么放在 API 层：求解器本身不应关心 HTTP/部署边界；这些规则属于产品服务
的安全护栏（防止一个请求占满线程/内存），也便于单元测试。

被谁调用：backend/server.py、tests。
"""

import os
import threading
from typing import Any, List, Optional, Sequence

from backend.solver_v2.evaluation.spec import POLICY_PROFILES

MAX_BODY_BYTES = int(os.environ.get("AICIVS_MAX_BODY_BYTES", str(8 * 1024 * 1024)))
MAX_SKUS = int(os.environ.get("AICIVS_MAX_SKUS", "500"))
MAX_CARTONS = int(os.environ.get("AICIVS_MAX_CARTONS", "50000"))
MIN_TIME_BUDGET_S = 1.0
MAX_TIME_BUDGET_S = float(os.environ.get("AICIVS_MAX_TIME_BUDGET_S", "120"))
MAX_ALT_TIME_BUDGET_S = float(os.environ.get("AICIVS_MAX_ALT_TIME_BUDGET_S", "60"))
MAX_ALTERNATIVES = int(os.environ.get("AICIVS_MAX_ALTERNATIVES", "3"))


class InputValidationError(ValueError):
    """请求参数不合法；error_response 会映射为 422 INPUT_INVALID。"""


def _invalid(message: str) -> None:
    raise InputValidationError(f"INPUT_INVALID: {message}")


def validate_time_budget(value: Any) -> float:
    try:
        budget = float(value)
    except (TypeError, ValueError):
        _invalid(f"timeBudgetSec 不是数字: {value!r}")
    if budget != budget or budget in (float("inf"), float("-inf")):
        _invalid("timeBudgetSec 必须是有限数字")
    if budget < MIN_TIME_BUDGET_S or budget > MAX_TIME_BUDGET_S:
        _invalid(f"timeBudgetSec 必须在 {MIN_TIME_BUDGET_S:g}~{MAX_TIME_BUDGET_S:g}s 之间")
    return budget


def validate_seed(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        _invalid(f"randomSeed 不是整数: {value!r}")


def validate_alternatives(value: Any) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        _invalid(f"alternatives 不是整数: {value!r}")
    if count < 0 or count > MAX_ALTERNATIVES:
        _invalid(f"alternatives 必须在 0~{MAX_ALTERNATIVES} 之间")
    return count


def validate_alternative_budget(value: Any, main_budget: float) -> float:
    try:
        budget = float(value)
    except (TypeError, ValueError):
        _invalid(f"alternativeBudgetSec 不是数字: {value!r}")
    if budget != budget or budget in (float("inf"), float("-inf")):
        _invalid("alternativeBudgetSec 必须是有限数字")
    if budget < MIN_TIME_BUDGET_S or budget > MAX_ALT_TIME_BUDGET_S:
        _invalid(f"alternativeBudgetSec 必须在 {MIN_TIME_BUDGET_S:g}~{MAX_ALT_TIME_BUDGET_S:g}s 之间")
    if budget > main_budget + 1e-9:
        _invalid("alternativeBudgetSec 不能大于主方案 timeBudgetSec")
    return budget


def validate_alternative_profiles(value: Any) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        _invalid("alternativeProfiles 必须是数组")
    known = set(POLICY_PROFILES)
    profiles: List[str] = []
    for item in value:
        key = str(item).upper()
        if key not in known:
            _invalid(f"未知策略档: {item!r}；可选 {sorted(known)}")
        profiles.append(key)
    return profiles


def validate_manifest_size(cargo_list: Sequence[Any]) -> None:
    if len(cargo_list) > MAX_SKUS:
        _invalid(f"SKU 数量 {len(cargo_list)} 超过上限 {MAX_SKUS}")
    total = 0
    for sku in cargo_list:
        qty = int(getattr(getattr(sku, "quantity", None), "required", 0) or 0)
        total += max(0, qty)
    if total > MAX_CARTONS:
        _invalid(f"总件数 {total} 超过上限 {MAX_CARTONS}")


class SolveGate:
    """全局 solve 并发闸门；默认 1，避免多请求在 GIL 下互相拖死。"""

    def __init__(self, max_concurrent: Optional[int] = None):
        if max_concurrent is None:
            try:
                max_concurrent = int(os.environ.get("AICIVS_MAX_CONCURRENT_SOLVES", "1"))
            except ValueError:
                max_concurrent = 1
        self.max_concurrent = max(1, int(max_concurrent))
        self._sem = threading.BoundedSemaphore(self.max_concurrent)

    def try_acquire(self) -> bool:
        return self._sem.acquire(blocking=False)

    def release(self) -> None:
        self._sem.release()


__all__ = [
    "InputValidationError",
    "MAX_BODY_BYTES",
    "MAX_SKUS",
    "MAX_CARTONS",
    "MIN_TIME_BUDGET_S",
    "MAX_TIME_BUDGET_S",
    "MAX_ALT_TIME_BUDGET_S",
    "MAX_ALTERNATIVES",
    "validate_time_budget",
    "validate_seed",
    "validate_alternatives",
    "validate_alternative_budget",
    "validate_alternative_profiles",
    "validate_manifest_size",
    "SolveGate",
]
