"""单元格级深度清洗与单位/复合尺寸解析工具。

用途:
    清洗客户 Excel/CSV 货单中常见的全角字符、不可见空格、占位符、
    内嵌单位数值（如 `56cm`、`560mm`、`670g`、`0.5T`）及单列复合尺寸
    （如 `560x280x360mm`、`0.56*0.28*0.36`）。

输入/输出:
    输入原始单元格值与目标物理量纲（length / weight）；
    输出标准化数值、识别出的单位及清洗元信息。

被谁调用:
    backend.importer.sheet_detector, backend.importer.column_mapper, backend.importer.anomaly_healer
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, List, Optional, Tuple


PLACEHOLDER_TOKENS = {
    "", "-", "—", "–", "--", "---", "/", "n/a", "na", "none", "null", "nil", "tbd", "无", "待定", "待补"
}

SUMMARY_ROW_RE = re.compile(
    r"^(?:总计|合计|共计|小计|总和|汇总|total|grand\s*total|sub\s*total|summary)\b",
    re.IGNORECASE,
)

GRAND_SUMMARY_ROW_RE = re.compile(
    r"^(?:总计|合计|共计|总和|汇总|total|grand\s*total|summary)\b",
    re.IGNORECASE,
)

LENGTH_UNIT_FACTORS = {
    "m": 1.0,
    "米": 1.0,
    "dm": 0.1,
    "分米": 0.1,
    "cm": 0.01,
    "厘米": 0.01,
    "公分": 0.01,
    "mm": 0.001,
    "毫米": 0.001,
    "in": 0.0254,
    "inch": 0.0254,
    "inches": 0.0254,
    '"': 0.0254,
    "″": 0.0254,
    "ft": 0.3048,
    "feet": 0.3048,
}

WEIGHT_UNIT_FACTORS = {
    "kg": 1.0,
    "kgs": 1.0,
    "公斤": 1.0,
    "千克": 1.0,
    "g": 0.001,
    "克": 0.001,
    "t": 1000.0,
    "ton": 1000.0,
    "tons": 1000.0,
    "吨": 1000.0,
    "lb": 0.45359237,
    "lbs": 0.45359237,
    "磅": 0.45359237,
}

_NUM_UNIT_RE = re.compile(
    r"^\s*([+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*([a-zA-Z\u4e00-\u9fff\"″]+)?\s*$"
)

_COMPOUND_DIM_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*[*xX×]\s*(\d+(?:\.\d+)?)\s*[*xX×]\s*(\d+(?:\.\d+)?)\s*([a-zA-Z\u4e00-\u9fff\"″]+)?\s*$"
)


def normalize_text(val: Any) -> str:
    """将全角字符、换行符及多余空白标准化为干净文本。"""
    if val is None:
        return ""
    text = unicodedata.normalize("NFKC", str(val))
    text = text.replace("\u00a0", " ").replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_placeholder(val: Any) -> bool:
    """判断单元格是否为无意义占位符。"""
    txt = normalize_text(val).lower()
    return txt in PLACEHOLDER_TOKENS


def is_summary_row_text(val: Any) -> bool:
    """判断文本是否为表尾合计/汇总标识（含小计）。"""
    txt = normalize_text(val)
    if not txt:
        return False
    return bool(SUMMARY_ROW_RE.match(txt))


def is_grand_summary_row_text(val: Any) -> bool:
    """判断文本是否为整表终结性的总计/合计/共计标识（不含小计）。"""
    txt = normalize_text(val)
    if not txt:
        return False
    return bool(GRAND_SUMMARY_ROW_RE.match(txt))


def parse_number_with_unit(val: Any, kind: str = "generic") -> Tuple[Optional[float], Optional[str]]:
    """解析单个数值及内嵌单位。

    Args:
        val: 原始单元格值
        kind: 'length' | 'weight' | 'generic'

    Returns:
        (raw_number, unit_key_or_None)
    """
    if val is None or isinstance(val, bool):
        return None, None
    if isinstance(val, (int, float)):
        if val != val:  # NaN
            return None, None
        return float(val), None
    txt = normalize_text(val)
    if not txt or txt.lower() in PLACEHOLDER_TOKENS:
        return None, None
    m = _NUM_UNIT_RE.match(txt)
    if not m:
        return None, None
    num = float(m.group(1).replace(",", ""))
    unit_raw = (m.group(2) or "").strip().lower()
    if not unit_raw:
        return num, None
    table = LENGTH_UNIT_FACTORS if kind == "length" else (WEIGHT_UNIT_FACTORS if kind == "weight" else {})
    if unit_raw in table:
        return num, unit_raw
    return num, unit_raw


def convert_to_meters(val: float, unit: Optional[str]) -> float:
    """按单位换算为米；未知单位默认按原值。"""
    if not unit:
        return val
    return val * LENGTH_UNIT_FACTORS.get(unit.lower(), 1.0)


def convert_to_kg(val: float, unit: Optional[str]) -> float:
    """按单位换算为千克；未知单位默认按原值。"""
    if not unit:
        return val
    return val * WEIGHT_UNIT_FACTORS.get(unit.lower(), 1.0)


def parse_compound_dims(val: Any) -> Optional[Tuple[float, float, float, Optional[str]]]:
    """解析单列复合尺寸（如 '560x280x360mm' 或 '0.56*0.28*0.36'）。"""
    txt = normalize_text(val)
    if not txt:
        return None
    m = _COMPOUND_DIM_RE.match(txt)
    if not m:
        return None
    a, b, c = float(m.group(1)), float(m.group(2)), float(m.group(3))
    unit = (m.group(4) or "").strip().lower() or None
    if unit and unit not in LENGTH_UNIT_FACTORS:
        unit = None
    return a, b, c, unit


def extract_unit_from_header(header: str, kind: str) -> Optional[str]:
    """从表头括号或后缀抽取单位，例如 '长(cm)' -> 'cm'，'单箱毛重(KG)' -> 'kg'。"""
    h = normalize_text(header).lower()
    table = LENGTH_UNIT_FACTORS if kind == "length" else WEIGHT_UNIT_FACTORS
    # 优先匹配括号内单位
    for m in re.finditer(r"[\(\[（【]([^)\]）】]+)[\)\]）】]", h):
        token = m.group(1).strip()
        if token in table:
            return token
    # 其次匹配末尾独立英文/中文单位词
    for u in sorted(table.keys(), key=len, reverse=True):
        if re.search(rf"(?<![a-z]){re.escape(u)}$", h):
            return u
    return None


def parse_all_numbers(val: Any) -> List[float]:
    """提取字符串中的所有数值，供兜底诊断使用。"""
    txt = normalize_text(val)
    return [float(x) for x in re.findall(r"[+-]?\d+(?:\.\d+)?", txt)]
