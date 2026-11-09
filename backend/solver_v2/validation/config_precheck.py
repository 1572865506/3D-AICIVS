"""
货单约束可满足性预检（manifest satisfiability pre-check）。

用途：在求解前检测"约束组合本身无解/互相冲突"的配置错误，把过去只能表现为
"装 0 件 + 饥饿"的静默失败，提前变成明确的配置诊断。

检查项（ERROR = 该 SKU 必然放不进；WARN = 语义冲突/降级，可继续求解）：
- E1 NO_LEGAL_ORIENTATION：策略过滤后没有任何合法朝向
- E2 FLAT_ON_TOP_WITHOUT_BASE：平放仅顶层，但货单缺少可作为底座的其它货物
- W1 ZONE_DIRECTIVE_CONFLICT：同一货单既要求"封柜门"又要求"放中间"（取更严的门区）
- W2 NO_TOP_STACK_VS_MAX_LAYERS："不可被压" 与 max_stack_layers>1 同时存在（禁压优先）
- W3 FLOOR_ONLY_SELF_STACK：must_be_on_floor 且 max_stack_layers>1（仅允许同款自堆叠）

被谁调用：backend/server.py（提交任务时预检，ERROR 直接 422）、
scripts/diagnose_case.py（诊断输出）。
"""
from typing import Any, Dict, List

from backend.solver_v2.domain.models import PackingRole, ZoneType


def _legal_modes(sku: Any) -> set:
    """返回该 SKU 在策略上允许的朝向家族集合（UPRIGHT/FLAT/SIDE）。"""
    pol = getattr(sku, "orientation_policy", None)
    if pol is None:
        return {"UPRIGHT"}
    rules = tuple(getattr(pol, "rules", ()) or ())
    if rules:
        modes = set()
        for r in rules:
            if getattr(r, "allowed_regions", ()):
                modes.add(str(getattr(r.orientation, "value", r.orientation)).upper())
        return modes
    modes = set()
    if getattr(pol, "allow_upright", True):
        modes.add("UPRIGHT")
    if getattr(pol, "allow_flat", False):
        modes.add("FLAT")
    if getattr(pol, "allow_side", False):
        modes.add("SIDE")
    return modes


def precheck_manifest(cargo_list: List[Any], container: Any) -> Dict[str, Any]:
    """
    返回 {ok: bool, errors: [...], warnings: [...], per_sku: [...]}。

    每条 issue: {code, severity, sku, message, hint}
    """
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    per_sku: List[Dict[str, Any]] = []

    has_stackable_other_base = len(cargo_list) > 1
    for sku in cargo_list:
        sid = getattr(sku, "sku_id", "?")
        pol = getattr(sku, "orientation_policy", None)
        stack = getattr(sku, "stacking_policy", None)
        req_text = getattr(sku, "source_requirement_text", "") or ""
        entry: Dict[str, Any] = {"sku": sid, "ok": True, "codes": []}

        modes = _legal_modes(sku)
        if not modes:
            errors.append({
                "code": "NO_LEGAL_ORIENTATION", "severity": "ERROR", "sku": sid,
                "message": f"{sid} 的朝向策略过滤后没有任何合法朝向（必然无法放置）",
                "hint": "检查 orientationPolicy 的规则/allowFlat/allowUpright 组合",
            })
            entry["ok"] = False
            entry["codes"].append("NO_LEGAL_ORIENTATION")

        # 平放仅顶层 且 无其它货物可作底座 → 永远放不上去
        if (pol is not None and getattr(pol, "flat_only_on_top", False)
                and modes <= {"FLAT"} and not has_stackable_other_base):
            errors.append({
                "code": "FLAT_ON_TOP_WITHOUT_BASE", "severity": "ERROR", "sku": sid,
                "message": f"{sid} 仅允许『平放且仅顶层』，但货单中没有可作为底座的其它货物",
                "hint": "允许该 SKU 立放/非顶层平放，或在货单中增加底层货物",
            })
            entry["ok"] = False
            entry["codes"].append("FLAT_ON_TOP_WITHOUT_BASE")

        # 区域指令冲突：同时要求门区与中间
        wants_door = ("封柜门" in req_text or "封门" in req_text
                      or getattr(sku, "target_zone", None) == ZoneType.DOOR
                      or PackingRole.DOOR_SEAL in tuple(getattr(sku, "packing_roles", ()) or ()))
        wants_middle = "放中间" in req_text or "中间" in req_text
        if wants_door and wants_middle:
            warnings.append({
                "code": "ZONE_DIRECTIVE_CONFLICT", "severity": "WARN", "sku": sid,
                "message": f"{sid} 同时要求『封柜门』与『放中间』，按门区（更严）执行",
                "hint": "确认业务意图；门区要求将覆盖中间区要求",
            })
            entry["codes"].append("ZONE_DIRECTIVE_CONFLICT")

        # 禁压 与 多层上限 并存 → 禁压优先，层数仅对同款自堆叠生效
        if (stack is not None and not getattr(stack, "allow_stacking_on_top", True)
                and (getattr(stack, "max_stack_layers", None) or 0) > 1):
            warnings.append({
                "code": "NO_TOP_STACK_VS_MAX_LAYERS", "severity": "WARN", "sku": sid,
                "message": f"{sid} 同时声明『不可被压』与 max_stack_layers>1，禁压优先",
                "hint": "如需同款自堆叠请确认 stackOnSelf；否则层数上限不会生效",
            })
            entry["codes"].append("NO_TOP_STACK_VS_MAX_LAYERS")

        # 必须落地 + 多层：仅允许同款自堆叠
        if (stack is not None and getattr(stack, "must_be_on_floor", False)
                and (getattr(stack, "max_stack_layers", None) or 0) > 1):
            warnings.append({
                "code": "FLOOR_ONLY_SELF_STACK", "severity": "WARN", "sku": sid,
                "message": f"{sid} 要求『必须落地』且允许堆 {stack.max_stack_layers} 层："
                           f"仅同款上方可自堆叠，其它货物不得垫底",
            })
            entry["codes"].append("FLOOR_ONLY_SELF_STACK")

        per_sku.append(entry)

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "per_sku": per_sku,
    }
