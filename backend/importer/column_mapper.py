"""多维置信度列映射与件数/箱数、单重/总重消歧模块。

用途:
    结合表头同义词评分、表头/单元格单位抽取、数值量级统计以及
    CBM/总重交叉勾稽验证，自动将任意客户表格列名映射到标准物理字段。

输入/输出:
    输入表头列表、样本数据行及可选的用户覆盖映射；
    输出各系统字段的最佳列索引、列名、置信度、识别单位与候选依据。

被谁调用:
    backend.importer.__init__, backend.importer.anomaly_healer
"""
from __future__ import annotations

import re
import statistics
from typing import Any, Dict, List, Optional, Tuple

from .cell_sanitizer import (
    convert_to_meters,
    extract_unit_from_header,
    normalize_text,
    parse_compound_dims,
    parse_number_with_unit,
)


FIELD_SYNONYMS: Dict[str, List[Tuple[re.Pattern[str], float]]] = {
    "sku_id": [
        (re.compile(r"^(sku|sku[_\s-]*id|货号|款号|编码|物料编码|item\s*no|part\s*no)$", re.I), 1.0),
        (re.compile(r"(sku|货号|料号|编码|item\s*code|model)", re.I), 0.78),
    ],
    "name": [
        (re.compile(r"^(产品名|产品名称|货物名称|品名|商品名称|货名|description|product\s*name|item\s*name)$", re.I), 1.0),
        (re.compile(r"(品名|产品名|产品|货物|名称|desc|title|name)", re.I), 0.80),
        (re.compile(r"(品牌|款式|型号|规格|机器配置|配置|物料|商品|brand|style|spec)", re.I), 0.65),
    ],
    "name_extra": [
        (re.compile(r"(机器配置|配置|规格型号|型号|款式|颜色|描述|spec|configuration|config|detail)", re.I), 0.75),
    ],
    "length": [
        (re.compile(r"^(长|长度|箱长|外箱长|length|len|l)(\(|（|$|\s)", re.I), 1.0),
        (re.compile(r"(长|length|\bl\b)", re.I), 0.72),
    ],
    "width": [
        (re.compile(r"^(宽|宽度|箱宽|外箱宽|width|wid|w)(\(|（|$|\s)", re.I), 1.0),
        (re.compile(r"(宽|width|\bw\b)", re.I), 0.72),
    ],
    "height": [
        (re.compile(r"^(高|高度|箱高|外箱高|height|hgt|h)(\(|（|$|\s)", re.I), 1.0),
        (re.compile(r"(高|height|\bh\b)", re.I), 0.72),
    ],
    "compound_dims": [
        (re.compile(r"(外箱尺寸|箱规|规格尺寸|尺寸|dimensions?|meas|size|l\s*[*x×]\s*w\s*[*x×]\s*h)", re.I), 0.92),
    ],
    "cartons": [
        (re.compile(r"(箱数|总箱数|ctns?|cartons?|boxes|pkgs?)", re.I), 1.0),
        (re.compile(r"(件数|外箱数|包装数)", re.I), 0.72),
        (re.compile(r"(数量|qty|quantity)", re.I), 0.55),
    ],
    "pcs": [
        (re.compile(r"(产品数量|总件数|总数量|pcs|pieces|units)", re.I), 0.92),
    ],
    "unit_weight": [
        (re.compile(r"(单箱毛重|单箱重|单重|每箱重|unit\s*g\.?w\.?|g\.?w\.?\s*/\s*ctn|weight\s*/\s*box)", re.I), 1.0),
        (re.compile(r"(毛重|重量|g\.?w\.?|weight)", re.I), 0.70),
        (re.compile(r"(净重|n\.?w\.?)", re.I), 0.55),
    ],
    "total_weight": [
        (re.compile(r"(总毛重|总重|总重量|total\s*g\.?w\.?|total\s*weight|gross\s*weight\s*total)", re.I), 0.98),
    ],
    "cbm": [
        (re.compile(r"(总体积|总立方|total\s*cbm|total\s*vol)", re.I), 1.0),
        (re.compile(r"(体积|cbm|volume|vol|m3|立方)", re.I), 0.90),
    ],
    "unit_cbm": [
        (re.compile(r"(单箱体积|单件体积|单位体积|每箱体积|unit\s*cbm|unit\s*vol|cbm\s*/\s*ctn)", re.I), 1.0),
        (re.compile(r"^(体积|cbm|vol|volume)(\(|（|$|\s)", re.I), 0.85),
    ],
    "requirement": [
        (re.compile(r"(摆放要求|装柜要求|装载要求|堆码要求|要求|注意事项|备注|requirement|remark|note|rule)", re.I), 0.95),
    ],
}


def _header_match_score(header: str, field: str) -> float:
    h = normalize_text(header)
    if not h:
        return 0.0
    hl = h.lower()
    # 防止 G.W. / N.W. / Total Weight 中的单字母 W 被误判为 width
    if field in ("length", "width", "height"):
        if re.search(r"(g\.?w\.?|n\.?w\.?|weight|毛重|净重|重量|kg|lbs|体积|cbm|箱数|数量|qty)", hl):
            return 0.0
    best = 0.0
    for pat, w in FIELD_SYNONYMS.get(field, []):
        if pat.search(h):
            best = max(best, w)
    # 避免 '原表CBM核对' 被误当成数值 CBM 列
    if field == "cbm" and ("核对" in h or "check" in h.lower()):
        best *= 0.25
    # 避免 '序列' 被当成 SKU
    if field == "sku_id" and h in ("序列", "序号", "no", "no.", "#"):
        best = 0.15
    # 若单位重量/体积列明确包含 "总"，降低成为 unit_* 的分
    if field == "unit_weight" and ("总" in h or "total" in h.lower()):
        best *= 0.30
    if field == "total_weight" and ("单箱" in h or "每箱" in h or "unit" in h.lower()):
        best *= 0.20
    if field == "unit_cbm" and ("总" in h or "total" in h.lower()):
        best *= 0.20
    if field == "cbm" and ("单箱" in h or "单件" in h or "每箱" in h or "unit" in h.lower()):
        best *= 0.25
    return best


def _infer_column_unit(headers: List[str], rows: List[Tuple[int, List[Any]]], col_idx: int, kind: str) -> str:
    """结合表头括号单位与单元格数据分布推断列默认单位。"""
    hdr_unit = extract_unit_from_header(headers[col_idx], kind)
    if hdr_unit:
        return hdr_unit

    nums: List[float] = []
    cell_units: List[str] = []
    for _, r in rows[:60]:
        val = r[col_idx] if col_idx < len(r) else None
        num, u = parse_number_with_unit(val, kind=kind)
        if num is not None and num > 0:
            nums.append(num)
        if u:
            cell_units.append(u)

    if cell_units:
        # 多数单元格自带单位时取众数
        return max(set(cell_units), key=cell_units.count)

    if not nums:
        return "m" if kind == "length" else "kg"

    med = statistics.median(nums)
    if kind == "length":
        if med > 100.0:
            return "mm"
        if med > 5.0:
            return "cm"
        return "m"
    else:
        if med > 2000.0:
            return "g"
        return "kg"


def _sample_numeric_ratio(rows: List[Tuple[int, List[Any]]], col_idx: int) -> float:
    sample = rows[:30]
    if not sample:
        return 0.0
    hits = 0
    for _, r in sample:
        v = r[col_idx] if col_idx < len(r) else None
        num, _ = parse_number_with_unit(v)
        if num is not None:
            hits += 1
    return hits / len(sample)


def _sample_compound_ratio(rows: List[Tuple[int, List[Any]]], col_idx: int) -> float:
    sample = rows[:30]
    if not sample:
        return 0.0
    hits = sum(1 for _, r in sample if parse_compound_dims(r[col_idx] if col_idx < len(r) else None) is not None)
    return hits / len(sample)


def map_columns(
    headers: List[str],
    rows: List[Tuple[int, List[Any]]],
    override_mapping: Optional[Dict[str, Optional[str]]] = None,
    override_units: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """计算每个目标系统字段的最佳列映射与置信度。"""
    override_mapping = override_mapping or {}
    override_units = override_units or {}
    used_cols: set[int] = set()
    result: Dict[str, Dict[str, Any]] = {}

    # 预计算每列的复合尺寸占比与数值占比
    num_ratios = [_sample_numeric_ratio(rows, c) for c in range(len(headers))]
    comp_ratios = [_sample_compound_ratio(rows, c) for c in range(len(headers))]

    def pick_best(field: str, require_numeric: bool = False, require_compound: bool = False) -> Optional[Tuple[int, float, str]]:
        # 用户显式覆盖优先
        if field in override_mapping:
            col_name = override_mapping[field]
            if col_name is None or col_name == "":
                return None
            if col_name in headers:
                c_idx = headers.index(col_name)
                return c_idx, 1.0, "用户手动指定"

        best_c = None
        best_sc = 0.0
        for c_idx, hdr in enumerate(headers):
            if c_idx in used_cols:
                continue
            sc = _header_match_score(hdr, field)
            if require_numeric and num_ratios[c_idx] < 0.35:
                sc *= 0.2
            if require_compound:
                sc = max(sc, comp_ratios[c_idx] * 0.95) if comp_ratios[c_idx] >= 0.4 else sc * 0.2
            if sc > best_sc:
                best_sc = sc
                best_c = c_idx
        if best_c is not None and best_sc >= 0.45:
            return best_c, round(min(1.0, best_sc), 2), "表头与数据特征自动匹配"
        return None

    # 1. 优先识别尺寸列或复合尺寸列
    for f in ("length", "width", "height"):
        picked = pick_best(f, require_numeric=True)
        if picked:
            c_idx, conf, reason = picked
            used_cols.add(c_idx)
            unit = override_units.get(f) or _infer_column_unit(headers, rows, c_idx, "length")
            result[f] = {"col_idx": c_idx, "source_col": headers[c_idx], "confidence": conf, "unit": unit, "reason": reason}

    if not all(k in result for k in ("length", "width", "height")):
        picked_comp = pick_best("compound_dims", require_compound=True)
        if picked_comp:
            c_idx, conf, reason = picked_comp
            used_cols.add(c_idx)
            unit = override_units.get("compound_dims") or extract_unit_from_header(headers[c_idx], "length") or "auto"
            result["compound_dims"] = {"col_idx": c_idx, "source_col": headers[c_idx], "confidence": conf, "unit": unit, "reason": reason}

    # 2. CBM 列与单箱体积列（用于后续件数 vs 箱数交叉验证及无尺寸体积反推）
    picked_cbm = pick_best("cbm", require_numeric=True)
    if picked_cbm:
        c_idx, conf, reason = picked_cbm
        used_cols.add(c_idx)
        result["cbm"] = {"col_idx": c_idx, "source_col": headers[c_idx], "confidence": conf, "unit": "m3", "reason": reason}

    picked_ucbm = pick_best("unit_cbm", require_numeric=True)
    if picked_ucbm:
        c_idx, conf, reason = picked_ucbm
        used_cols.add(c_idx)
        result["unit_cbm"] = {"col_idx": c_idx, "source_col": headers[c_idx], "confidence": conf, "unit": "m3", "reason": reason}

    # 3. 重量列（单箱重优先，总重兜底，同时辅助箱数交叉消歧）
    for f in ("unit_weight", "total_weight"):
        picked = pick_best(f, require_numeric=True)
        if picked:
            c_idx, conf, reason = picked
            used_cols.add(c_idx)
            unit = override_units.get(f) or _infer_column_unit(headers, rows, c_idx, "weight")
            result[f] = {"col_idx": c_idx, "source_col": headers[c_idx], "confidence": conf, "unit": unit, "reason": reason}

    # 4. 箱数列（cartons）优先于件数列（pcs），并做 CBM / 单箱体积 / 总毛重交叉校验
    picked_ctn = pick_best("cartons", require_numeric=True)
    if picked_ctn:
        c_idx, conf, reason = picked_ctn
        if "cartons" not in override_mapping:
            best_cross_c = c_idx
            best_err = 1e9
            cross_reason = reason
            for cand_c in range(len(headers)):
                if cand_c in used_cols or num_ratios[cand_c] < 0.5:
                    continue
                if _header_match_score(headers[cand_c], "cartons") < 0.45 and _header_match_score(headers[cand_c], "pcs") < 0.45:
                    continue
                errs: List[float] = []
                mode_label = ""
                if "cbm" in result and all(k in result for k in ("length", "width", "height")):
                    cbm_c = result["cbm"]["col_idx"]
                    lc, wc, hc = result["length"]["col_idx"], result["width"]["col_idx"], result["height"]["col_idx"]
                    lu, wu, hu = result["length"]["unit"], result["width"]["unit"], result["height"]["unit"]
                    mode_label = "通过 L×W×H×箱数≈CBM 交叉验证消歧"
                    for _, r in rows[:20]:
                        l_v, l_cu = parse_number_with_unit(r[lc], "length")
                        w_v, w_cu = parse_number_with_unit(r[wc], "length")
                        h_v, h_cu = parse_number_with_unit(r[hc], "length")
                        q_v, _ = parse_number_with_unit(r[cand_c])
                        cbm_v, _ = parse_number_with_unit(r[cbm_c])
                        if l_v and w_v and h_v and q_v and cbm_v and cbm_v > 0:
                            lm = convert_to_meters(l_v, l_cu or lu)
                            wm = convert_to_meters(w_v, w_cu or wu)
                            hm = convert_to_meters(h_v, h_cu or hu)
                            calc = lm * wm * hm * q_v
                            errs.append(abs(calc - cbm_v) / cbm_v)
                elif "cbm" in result and "unit_cbm" in result:
                    cbm_c = result["cbm"]["col_idx"]
                    ucbm_c = result["unit_cbm"]["col_idx"]
                    mode_label = "通过 单箱体积×箱数≈总体积 交叉验证消歧"
                    for _, r in rows[:20]:
                        u_v, _ = parse_number_with_unit(r[ucbm_c])
                        q_v, _ = parse_number_with_unit(r[cand_c])
                        cbm_v, _ = parse_number_with_unit(r[cbm_c])
                        if u_v and q_v and cbm_v and cbm_v > 0:
                            errs.append(abs(u_v * q_v - cbm_v) / cbm_v)
                elif "unit_weight" in result and "total_weight" in result:
                    uw_c = result["unit_weight"]["col_idx"]
                    tw_c = result["total_weight"]["col_idx"]
                    mode_label = "通过 单箱重×箱数≈总毛重 交叉验证消歧"
                    for _, r in rows[:20]:
                        uw_v, _ = parse_number_with_unit(r[uw_c], "weight")
                        q_v, _ = parse_number_with_unit(r[cand_c])
                        tw_v, _ = parse_number_with_unit(r[tw_c], "weight")
                        if uw_v and q_v and tw_v and tw_v > 0:
                            errs.append(abs(uw_v * q_v - tw_v) / tw_v)
                if errs:
                    med_err = statistics.median(errs)
                    if med_err < best_err:
                        best_err = med_err
                        best_cross_c = cand_c
                        cross_reason = mode_label
            if best_err < 0.10:
                if best_cross_c != c_idx:
                    c_idx = best_cross_c
                conf = 0.98
                reason = cross_reason
        used_cols.add(c_idx)
        result["cartons"] = {"col_idx": c_idx, "source_col": headers[c_idx], "confidence": conf, "unit": "boxes", "reason": reason}

    # 5. 品名、补充描述、SKU 与摆放要求
    for f in ("name", "name_extra", "sku_id", "requirement"):
        picked = pick_best(f, require_numeric=False)
        if picked:
            c_idx, conf, reason = picked
            used_cols.add(c_idx)
            result[f] = {"col_idx": c_idx, "source_col": headers[c_idx], "confidence": conf, "unit": None, "reason": reason}

    return result
