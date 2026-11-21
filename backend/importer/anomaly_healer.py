"""黄金三角交叉校验、异常自愈与三态分级拦截引擎。

用途:
    对列映射后的每行客户数据执行：
    1) 尺寸与隐形单位漂移纠偏（利用物理上限 + 原表 CBM 黄金三角试算）
    2) 重量缺失、总重/单重倒挂与 g/kg 单位误填纠偏及密度估算兜底
    3) 缺单维反推、小数箱数取整与 0 箱配件行折叠
    4) 输出三态分级（OK / AUTO_FIXED / NEED_CONFIRM / BLOCKED）供前端交互。

输入/输出:
    输入列映射结果、数据行及目标集装箱内部尺寸；
    输出标准化 SKU 列表、被折叠的配件/忽略行、以及整单健康摘要。

被谁调用:
    backend.importer.__init__
"""
from __future__ import annotations

import math
import re
import statistics
from typing import Any, Dict, List, Optional, Tuple

from .cell_sanitizer import (
    convert_to_kg,
    convert_to_meters,
    is_placeholder,
    normalize_text,
    parse_compound_dims,
    parse_number_with_unit,
)
from .rule_normalizer import normalize_placement_rules


DEFAULT_CARDBOARD_DENSITY_KG_M3 = 180.0
MAX_REASONABLE_DENSITY_KG_M3 = 1500.0
MIN_REASONABLE_DENSITY_KG_M3 = 10.0

_LAPTOP_CAT_RE = re.compile(r"(笔记本|laptop|notebook|平板|tablet|ipad)", re.I)
_DISPLAY_CAT_RE = re.compile(
    r"(屏|显示器|monitor|screen|液晶|一体机|面板|panel|\d+(?:\.\d+)?\s*(?:寸|inch|\"|″))",
    re.I,
)
_LONG_CAT_RE = re.compile(r"(管|杆|架|轨|条|线槽|pipe|rod|rail|bar)", re.I)


def _fits_container(l: float, w: float, h: float, cont_dims: Tuple[float, float, float]) -> bool:
    """判断单箱在允许任意旋转时能否放进目标集装箱（最保守几何上限）。"""
    box_sorted = sorted([l, w, h])
    cont_sorted = sorted(cont_dims)
    return all(b <= c + 1e-4 for b, c in zip(box_sorted, cont_sorted))


def _infer_dims_from_volume(
    unit_vol: float,
    context_text: str,
    cont_dims: Tuple[float, float, float],
) -> Tuple[float, float, float, str]:
    """当原始货单完全缺失 L/W/H 仅有单箱体积 V 时，按品类特征与工业标准箱型长宽比反推尺寸。"""
    if _LAPTOP_CAT_RE.search(context_text):
        r_l, r_w, r_h = 1.40, 1.00, 0.76
        ratio_desc = "便携设备标准箱型比(1.40:1.00:0.76)"
    elif _DISPLAY_CAT_RE.search(context_text):
        if unit_vol >= 0.08:
            r_l, r_w, r_h = 1.45, 1.02, 0.90
            ratio_desc = "显示套件合装标准箱型比(1.45:1.02:0.90)"
        else:
            r_l, r_w, r_h = 1.48, 0.98, 0.72
            ratio_desc = "显示屏单件标准箱型比(1.48:0.98:0.72)"
    elif _LONG_CAT_RE.search(context_text):
        r_l, r_w, r_h = 2.20, 0.80, 0.70
        ratio_desc = "长条形标准箱型比(2.20:0.80:0.70)"
    else:
        r_l, r_w, r_h = 1.35, 1.00, 0.80
        ratio_desc = "ISO通用瓦楞箱黄金比(1.35:1.00:0.80)"

    scale = (unit_vol / (r_l * r_w * r_h)) ** (1.0 / 3.0)
    max_c, mid_c, min_c = sorted(cont_dims, reverse=True)
    l = min(max(0.03, round(scale * r_l, 3)), round(max_c * 0.95, 3))
    w = min(max(0.03, round(scale * r_w, 3)), round(mid_c * 0.95, 3))
    h = max(0.03, round(unit_vol / max(1e-9, l * w), 4))
    if h > min_c * 0.95:
        h = round(min_c * 0.95, 3)
        w = max(0.03, round(unit_vol / max(1e-9, l * h), 4))
    return l, w, h, ratio_desc


def _try_heal_row_dims(
    l: Optional[float],
    w: Optional[float],
    h: Optional[float],
    cartons: int,
    orig_cbm: Optional[float],
    cont_dims: Tuple[float, float, float],
    unit_cbm: Optional[float] = None,
    context_text: str = "",
) -> Tuple[Optional[float], Optional[float], Optional[float], List[Dict[str, Any]], bool]:
    """尝试修复单行隐形单位漂移、小数点错位、单维缺失或全维缺失体积反推。"""
    fixes: List[Dict[str, Any]] = []
    dims = [l, w, h]
    missing_idxs = [i for i, v in enumerate(dims) if v is None or v <= 0]
    inferred_from_vol = False

    # 0. 若长宽高全缺，但存在单箱体积或总体积+箱数，执行通用体积反推
    if len(missing_idxs) == 3:
        u_vol = unit_cbm if (unit_cbm and unit_cbm > 0) else (
            (orig_cbm / cartons) if (orig_cbm and orig_cbm > 0 and cartons > 0) else None
        )
        if u_vol and u_vol > 1e-6:
            il, iw, ih, ratio_desc = _infer_dims_from_volume(u_vol, context_text, cont_dims)
            dims = [il, iw, ih]
            missing_idxs = []
            inferred_from_vol = True
            fixes.append({
                "code": "INFERRED_DIMS_FROM_VOLUME",
                "level": "WARN",
                "field": "dims",
                "message": f"原始货单缺失长宽高，已按单箱体积({u_vol:.6g}m³)及{ratio_desc}反推为 {il:.3f}×{iw:.3f}×{ih:.4f}m",
            })

    # 1. 若仅缺一维且有 orig_cbm 与 cartons，反推缺失维
    if len(missing_idxs) == 1 and orig_cbm and orig_cbm > 0 and cartons > 0:
        known = [v for v in dims if v is not None and v > 0]
        inferred = (orig_cbm / cartons) / max(1e-9, known[0] * known[1])
        if 0.01 <= inferred <= max(cont_dims):
            idx = missing_idxs[0]
            axis_name = ("长", "宽", "高")[idx]
            dims[idx] = round(inferred, 4)
            inferred_from_vol = True
            fixes.append({
                "code": "ESTIMATED_DIM",
                "level": "WARN",
                "field": ("l", "w", "h")[idx],
                "message": f"缺失{axis_name}，按 CBM({orig_cbm})÷箱数({cartons}) 反推为 {dims[idx]}m",
            })
            missing_idxs = []

    if missing_idxs:
        return dims[0], dims[1], dims[2], fixes, inferred_from_vol

    lv, wv, hv = float(dims[0]), float(dims[1]), float(dims[2])  # type: ignore[arg-type]
    # 2. 检查是否超柜门/超长，或实算体积与原表 CBM 存在数量级偏差
    calc_cbm = lv * wv * hv * max(1, cartons)
    cbm_ratio_bad = bool(orig_cbm and orig_cbm > 0 and (calc_cbm / orig_cbm > 3.0 or orig_cbm / max(1e-9, calc_cbm) > 3.0))
    oversize = not _fits_container(lv, wv, hv, cont_dims)

    if oversize or cbm_ratio_bad:
        # 试算整行单位误填（cm / mm / inch / dm / 小数点错位）
        candidates = [
            (0.01, "疑误填 cm，自动按 ÷100 换算为 m"),
            (0.001, "疑误填 mm，自动按 ÷1000 换算为 m"),
            (0.0254, "疑误填 inch，自动按 ×0.0254 换算为 m"),
            (0.1, "疑小数点多移一位，按 ×0.1 修正"),
            (10.0, "疑小数点少移一位，按 ×10 修正"),
        ]
        for factor, desc in candidates:
            nl, nw, nh = round(lv * factor, 4), round(wv * factor, 4), round(hv * factor, 4)
            if not _fits_container(nl, nw, nh, cont_dims) or min(nl, nw, nh) < 0.015:
                continue
            new_cbm = nl * nw * nh * max(1, cartons)
            if orig_cbm and orig_cbm > 0:
                if abs(new_cbm - orig_cbm) / orig_cbm <= 0.08:
                    fixes.append({
                        "code": "AUTO_UNIT_DRIFT",
                        "level": "AUTO_FIXED",
                        "field": "dims",
                        "message": f"{desc}（({lv},{wv},{hv}) → ({nl},{nw},{nh})m，与原表 CBM 一致）",
                    })
                    return nl, nw, nh, fixes, inferred_from_vol
            elif oversize:
                fixes.append({
                    "code": "AUTO_UNIT_DRIFT",
                    "level": "NEED_CONFIRM",
                    "field": "dims",
                    "message": f"原尺寸({lv},{wv},{hv})超出柜体极限，{desc} 为 ({nl},{nw},{nh})m，请确认",
                })
                return nl, nw, nh, fixes, inferred_from_vol

    return round(lv, 4), round(wv, 4), round(hv, 4), fixes, inferred_from_vol


def heal_and_build_manifest(
    headers: List[str],
    rows: List[Tuple[int, List[Any]]],
    mapping: Dict[str, Dict[str, Any]],
    container_dims: Tuple[float, float, float] = (12.032, 2.352, 2.698),
) -> Dict[str, Any]:
    """清洗、转换并校验所有数据行，生成三态分级结果。"""
    items: List[Dict[str, Any]] = []
    accessory_rows: List[Dict[str, Any]] = []
    valid_densities: List[float] = []

    def cell_val(row: List[Any], field: str) -> Any:
        m = mapping.get(field)
        if not m:
            return None
        idx = m["col_idx"]
        return row[idx] if idx < len(row) else None

    def col_unit(field: str, default: str) -> str:
        m = mapping.get(field)
        return (m.get("unit") if m else None) or default

    # 第一遍：收集有效密度中位数，供后续缺失重量行合理估算
    for _, row in rows:
        l_num, lu = parse_number_with_unit(cell_val(row, "length"), "length")
        w_num, wu = parse_number_with_unit(cell_val(row, "width"), "length")
        h_num, hu = parse_number_with_unit(cell_val(row, "height"), "length")
        if (l_num is None or w_num is None or h_num is None) and "compound_dims" in mapping:
            comp = parse_compound_dims(cell_val(row, "compound_dims"))
            if comp:
                l_num, w_num, h_num, cu = comp
                lu = wu = hu = cu or (None if col_unit("compound_dims", "auto") == "auto" else col_unit("compound_dims", "m"))
        if not (l_num and w_num and h_num):
            continue
        lm = convert_to_meters(l_num, lu or col_unit("length", "m"))
        wm = convert_to_meters(w_num, wu or col_unit("width", "m"))
        hm = convert_to_meters(h_num, hu or col_unit("height", "m"))
        vol = lm * wm * hm
        if vol <= 1e-6 or not _fits_container(lm, wm, hm, container_dims):
            continue
        wt_num, wtu = parse_number_with_unit(cell_val(row, "unit_weight"), "weight")
        if wt_num and wt_num > 0:
            wkg = convert_to_kg(wt_num, wtu or col_unit("unit_weight", "kg"))
            dens = wkg / vol
            if MIN_REASONABLE_DENSITY_KG_M3 <= dens <= MAX_REASONABLE_DENSITY_KG_M3:
                valid_densities.append(dens)

    fallback_density = round(statistics.median(valid_densities), 1) if valid_densities else DEFAULT_CARDBOARD_DENSITY_KG_M3

    # 第二遍：逐行解析、纠偏、生成三态记录
    last_valid_name: str = ""
    seen_skus: Dict[str, int] = {}

    for seq_idx, (excel_row, row) in enumerate(rows, start=1):
        row_issues: List[Dict[str, Any]] = []
        raw_sku_cell = normalize_text(cell_val(row, "sku_id"))
        raw_sku = "" if is_placeholder(raw_sku_cell) else raw_sku_cell

        primary_name_cell = normalize_text(cell_val(row, "name"))
        primary_name = "" if is_placeholder(primary_name_cell) else primary_name_cell
        extra_name_cell = normalize_text(cell_val(row, "name_extra"))
        extra_name = "" if is_placeholder(extra_name_cell) else extra_name_cell

        if primary_name and extra_name and extra_name not in primary_name:
            if len(primary_name) <= 4:
                raw_name = f"{primary_name} - {extra_name}"
            else:
                raw_name = primary_name
        else:
            raw_name = primary_name or extra_name

        context_text = f"{primary_name} {extra_name}".strip()

        # 预提取尺寸、体积与重量，用于判定空样品行或合并续行
        l_num, lu = parse_number_with_unit(cell_val(row, "length"), "length")
        w_num, wu = parse_number_with_unit(cell_val(row, "width"), "length")
        h_num, hu = parse_number_with_unit(cell_val(row, "height"), "length")
        if (l_num is None or w_num is None or h_num is None) and "compound_dims" in mapping:
            comp = parse_compound_dims(cell_val(row, "compound_dims"))
            if comp:
                l_num, w_num, h_num, cu = comp
                lu = wu = hu = cu
                if not cu and col_unit("compound_dims", "auto") == "auto":
                    inferred_cu = "mm" if max(l_num, w_num, h_num) > 100 else ("cm" if max(l_num, w_num, h_num) > 5 else "m")
                    lu = wu = hu = inferred_cu
                elif not cu:
                    lu = wu = hu = col_unit("compound_dims", "m")

        lm = convert_to_meters(l_num, lu or col_unit("length", "m")) if l_num and l_num > 0 else None
        wm = convert_to_meters(w_num, wu or col_unit("width", "m")) if w_num and w_num > 0 else None
        hm = convert_to_meters(h_num, hu or col_unit("height", "m")) if h_num and h_num > 0 else None
        orig_cbm, _ = parse_number_with_unit(cell_val(row, "cbm"))
        unit_cbm, _ = parse_number_with_unit(cell_val(row, "unit_cbm"))
        wt_num, wtu = parse_number_with_unit(cell_val(row, "unit_weight"), "weight")
        tot_wt_num, twtu = parse_number_with_unit(cell_val(row, "total_weight"), "weight")
        qty_raw, _ = parse_number_with_unit(cell_val(row, "cartons"))

        has_any_dim = bool(lm or wm or hm)
        has_any_vol = bool((orig_cbm and orig_cbm > 0) or (unit_cbm and unit_cbm > 0))
        has_any_wt = bool((wt_num and wt_num > 0) or (tot_wt_num and tot_wt_num > 0))

        # 合并单元格续行自动继承上一行品名
        if not raw_name:
            if last_valid_name and (qty_raw or has_any_vol or has_any_wt):
                raw_name = f"{last_valid_name} (续)"
                context_text = raw_name
                row_issues.append({
                    "code": "INHERITED_MERGED_ROW",
                    "level": "AUTO_FIXED",
                    "field": "name",
                    "message": f"合并续行缺失品名，已自动继承上一行品名“{last_valid_name}”",
                })
            else:
                raw_name = raw_sku or f"货物-{len(items) + 1}"

        req_info = normalize_placement_rules(cell_val(row, "requirement"), context_text or raw_name)

        # 箱数解析、样品空行跳过与小数取整
        if qty_raw is None or qty_raw <= 0:
            if req_info["is_accessory_note"] or qty_raw == 0:
                accessory_rows.append({
                    "excel_row": excel_row,
                    "name": raw_name,
                    "reason": "箱数为 0 或标注随主箱附带，不独立占用柜容",
                })
                continue
            if not has_any_dim and not has_any_vol and not has_any_wt:
                accessory_rows.append({
                    "excel_row": excel_row,
                    "name": raw_name,
                    "reason": "无有效箱数、重量及体积（样品/非独立装箱行），已自动跳过",
                })
                continue
            cartons = 0
            row_issues.append({"code": "MISSING_CARTONS", "level": "BLOCKED", "field": "quantity", "message": "缺失有效箱数"})
        else:
            frac = qty_raw - math.floor(qty_raw)
            if 1e-4 < frac < 0.9999:
                cartons = int(math.ceil(qty_raw))
                row_issues.append({
                    "code": "CEIL_CARTONS",
                    "level": "AUTO_FIXED",
                    "field": "quantity",
                    "message": f"小数箱数 {qty_raw:g} 已向上取整为 {cartons} 箱",
                })
            else:
                cartons = int(round(qty_raw))

        if raw_name and not raw_name.endswith(" (续)"):
            last_valid_name = raw_name

        item_seq = len(items) + 1
        base_sku = raw_sku if raw_sku and not raw_sku.isdigit() else f"SKU-{item_seq:02d}"
        if base_sku in seen_skus:
            seen_skus[base_sku] += 1
            sku_id = f"{base_sku}-{seen_skus[base_sku]}"
            row_issues.append({
                "code": "DUPLICATE_SKU_RENAMED",
                "level": "WARN",
                "field": "sku",
                "message": f"原表存在重复编号 {base_sku}，已自动重命名为 {sku_id}",
            })
        else:
            seen_skus[base_sku] = 1
            sku_id = base_sku

        if orig_cbm is None and unit_cbm and unit_cbm > 0 and cartons > 0:
            orig_cbm = round(unit_cbm * cartons, 6)

        healed_l, healed_w, healed_h, dim_fixes, inferred_from_vol = _try_heal_row_dims(
            lm, wm, hm, cartons, orig_cbm, container_dims, unit_cbm=unit_cbm, context_text=context_text or raw_name
        )
        row_issues.extend(dim_fixes)

        if not (healed_l and healed_w and healed_h and healed_l > 0 and healed_w > 0 and healed_h > 0):
            row_issues.append({"code": "MISSING_DIMS", "level": "BLOCKED", "field": "dims", "message": "长/宽/高尺寸不完整，请手动补全"})
            healed_l = healed_l or 0.0
            healed_w = healed_w or 0.0
            healed_h = healed_h or 0.0
        elif not _fits_container(healed_l, healed_w, healed_h, container_dims):
            row_issues.append({
                "code": "BLOCK_OVERSIZE",
                "level": "BLOCKED",
                "field": "dims",
                "message": f"单箱尺寸 ({healed_l}×{healed_w}×{healed_h}m) 超过柜体物理极限，请核对单位或尺寸",
            })

        # 原表 CBM 偏差提示
        calc_cbm = healed_l * healed_w * healed_h * max(0, cartons)
        if orig_cbm and orig_cbm > 0 and calc_cbm > 0:
            diff_ratio = abs(calc_cbm - orig_cbm) / orig_cbm
            if diff_ratio > 0.05 and not any(x["code"] == "AUTO_UNIT_DRIFT" for x in dim_fixes):
                row_issues.append({
                    "code": "CBM_MISMATCH",
                    "level": "NEED_CONFIRM",
                    "field": "cbm",
                    "message": f"实算体积 {calc_cbm:.3f}m³ 与原表 CBM({orig_cbm:.3f}) 偏差 {diff_ratio*100:.1f}%",
                })

        # 重量解析与异常自愈
        unit_wt = convert_to_kg(wt_num, wtu or col_unit("unit_weight", "kg")) if wt_num and wt_num > 0 else None
        tot_wt = convert_to_kg(tot_wt_num, twtu or col_unit("total_weight", "kg")) if tot_wt_num and tot_wt_num > 0 else None

        if unit_wt is None and tot_wt is not None and cartons > 0:
            unit_wt = round(tot_wt / cartons, 3)
            row_issues.append({
                "code": "WEIGHT_FROM_TOTAL",
                "level": "AUTO_FIXED",
                "field": "weight",
                "message": f"缺单箱重，已按总毛重({tot_wt:g}kg)÷箱数({cartons}) 自动推算为 {unit_wt}kg",
            })

        box_vol = healed_l * healed_w * healed_h
        if unit_wt is not None and box_vol > 1e-5:
            dens = unit_wt / box_vol
            if dens > MAX_REASONABLE_DENSITY_KG_M3:
                if cartons > 1 and MIN_REASONABLE_DENSITY_KG_M3 <= (unit_wt / cartons) / box_vol <= MAX_REASONABLE_DENSITY_KG_M3:
                    fixed_wt = round(unit_wt / cartons, 3)
                    row_issues.append({
                        "code": "WEIGHT_SWAPPED_TOTAL",
                        "level": "NEED_CONFIRM",
                        "field": "weight",
                        "message": f"单箱重 {unit_wt:g}kg 密度过高({dens:.0f}kg/m³)，疑为总重误填，建议修正为 {fixed_wt}kg",
                    })
                    unit_wt = fixed_wt
                elif MIN_REASONABLE_DENSITY_KG_M3 <= (unit_wt / 1000.0) / box_vol <= MAX_REASONABLE_DENSITY_KG_M3:
                    fixed_wt = round(unit_wt / 1000.0, 3)
                    row_issues.append({
                        "code": "WEIGHT_UNIT_G",
                        "level": "AUTO_FIXED",
                        "field": "weight",
                        "message": f"单箱重 {unit_wt:g} 疑为克(g)，已自动折算为 {fixed_wt}kg",
                    })
                    unit_wt = fixed_wt

        if unit_wt is not None and tot_wt is not None and cartons > 0:
            calc_tot_wt = unit_wt * cartons
            wt_diff_ratio = abs(calc_tot_wt - tot_wt) / max(calc_tot_wt, tot_wt, 1e-6)
            if wt_diff_ratio > 0.05 and not any(x["code"] in ("WEIGHT_SWAPPED_TOTAL", "WEIGHT_UNIT_G") for x in row_issues):
                row_issues.append({
                    "code": "WEIGHT_TOTAL_MISMATCH",
                    "level": "WARN",
                    "field": "weight",
                    "message": f"单箱重({unit_wt:g}kg)×箱数({cartons})={calc_tot_wt:g}kg 与原表总毛重({tot_wt:g}kg)存在微差，已按单箱毛重计",
                })

        if unit_wt is None or unit_wt <= 0:
            est_wt = round(max(0.2, box_vol * fallback_density), 2) if box_vol > 0 else 5.0
            unit_wt = est_wt
            row_issues.append({
                "code": "ESTIMATED_WEIGHT",
                "level": "NEED_CONFIRM",
                "field": "weight",
                "message": f"缺失单箱重量，已按货单中位密度({fallback_density}kg/m³)估算为 {est_wt}kg（未填0）",
            })

        levels = [x["level"] for x in row_issues]
        if "BLOCKED" in levels:
            status = "BLOCKED"
        elif "NEED_CONFIRM" in levels:
            status = "NEED_CONFIRM"
        elif "AUTO_FIXED" in levels or "WARN" in levels:
            status = "AUTO_FIXED"
        else:
            status = "OK"

        items.append({
            "excel_row": excel_row,
            "sku": sku_id,
            "name": raw_name,
            "w": round(healed_w, 4),
            "d": round(healed_l, 4),
            "h": round(healed_h, 4),
            "l": round(healed_l, 4),
            "weight": round(unit_wt, 3),
            "quantity": cartons,
            "inferred_dimensions": inferred_from_vol,
            "requirement": req_info["requirement"],
            "logistics_note": req_info.get("logistics_note", ""),
            "rule_tags": req_info["rule_tags"],
            "placement_rules": req_info["placement_rules"],
            "orig_cbm": round(orig_cbm, 6) if orig_cbm is not None else None,
            "calc_cbm": round(calc_cbm, 6),
            "status": status,
            "issues": row_issues,
        })

    cont_vol = container_dims[0] * container_dims[1] * container_dims[2]
    total_cartons = sum(it["quantity"] for it in items)
    total_cbm = round(sum(it["calc_cbm"] for it in items), 3)
    total_wt = round(sum(it["weight"] * it["quantity"] for it in items), 2)
    blocked_count = sum(1 for it in items if it["status"] == "BLOCKED")
    confirm_count = sum(1 for it in items if it["status"] in ("NEED_CONFIRM", "AUTO_FIXED"))

    return {
        "items": items,
        "accessory_rows": accessory_rows,
        "summary": {
            "sku_count": len(items),
            "total_cartons": total_cartons,
            "total_cbm": total_cbm,
            "container_cbm": round(cont_vol, 2),
            "volume_ratio_pct": round(total_cbm / max(1e-6, cont_vol) * 100.0, 1),
            "total_weight_kg": total_wt,
            "blocked_count": blocked_count,
            "warning_or_fixed_count": confirm_count,
            "ok_count": len(items) - blocked_count - confirm_count,
            "can_submit": blocked_count == 0 and len(items) > 0,
        },
    }
