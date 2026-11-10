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

    # 多点卸货站序一致性：要么全不设，要么全部设置（混用会让未设置者不受区段约束）
    _stops = [(getattr(c, "sku_id", "?"), getattr(c, "unload_stop", None)) for c in cargo_list]
    _set = [(sid, st) for sid, st in _stops if st is not None]
    if _set and len(_set) != len(_stops):
        missing = [sid for sid, st in _stops if st is None]
        warnings.append({
            "code": "UNLOAD_STOP_PARTIAL", "severity": "WARN", "sku": ",".join(missing[:5]),
            "message": f"{len(missing)} 个 SKU 未设置卸货站序（{missing[:3]}），它们不受多站区段约束",
            "hint": "多点配送请为所有 SKU 设置 unloadStop（1 = 第一站，需靠门）",
        })
    if len({st for _, st in _set}) == 1 and _set:
        warnings.append({
            "code": "UNLOAD_STOP_SINGLE", "severity": "WARN", "sku": "",
            "message": "所有 SKU 卸货站序相同（相当于单站），多站分区不会生效",
            "hint": "单站配送可忽略；多站请设置不同站序",
        })

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

        # 易碎件：未声明承压能力时提示"按可承压处理"
        _hp = getattr(getattr(sku, "cargo_profile", None), "handling_policy", None)
        if _hp is not None and getattr(_hp, "fragile", False):
            _can_bear = True
            if stack is not None:
                if not getattr(stack, "allow_stacking_on_top", True):
                    _can_bear = False
                _mb = getattr(stack, "max_bearing_kg", None)
                if _mb is not None and float(_mb) <= 0:
                    _can_bear = False
            if _can_bear and getattr(stack, "max_bearing_kg", None) is None:
                warnings.append({
                    "code": "FRAGILE_NO_BEARING_DECLARED", "severity": "WARN", "sku": sid,
                    "message": f"{sid} 标记为易碎（含玻璃）但未声明承压能力，按『可承压』处理",
                    "hint": "若该件不可承压，请设置 maxBearingKg=0 或 allowStackingOnTop=false；"
                            "若可承压（如含玻璃但结构可承重），保持现状即可",
                })
                entry["codes"].append("FRAGILE_NO_BEARING_DECLARED")
            elif not _can_bear:
                entry["codes"].append("FRAGILE_NOT_BEARING_ENFORCED")
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
