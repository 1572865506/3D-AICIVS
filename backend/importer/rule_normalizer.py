"""中文/英文摆放要求自然语言翻译器与配件行识别。

用途:
    将客户货单中的自然语言备注（如“最后放”、“不可压”、“正立/向上”、
    “最多堆3层”、“放底层”）结构化为标准 placement_rules 字典，并生成
    前端展示标签。

输入/输出:
    输入原始摆放要求与品名备注文本；
    输出 placement_rules、规则标签列表、标准 requirement 文本及是否为配件附带行。

被谁调用:
    backend.importer.anomaly_healer
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from .cell_sanitizer import is_placeholder, normalize_text


_DOOR_RE = re.compile(r"(最后放|最后装|封门|贴门|放门口|近门|门口|door|last)", re.I)
_REAR_RE = re.compile(r"(最里面|最深处|靠墙里|最先放|最先装|rear|deepest|first)", re.I)
_FLOOR_RE = re.compile(r"(放底层|贴地|放最下|底层|重货|floor\s*only|bottom|heavy)", re.I)
_NO_STACK_RE = re.compile(r"(不可压|不能压|禁止堆压|不可叠放|不压|放最上|顶层|易碎|fragile|no\s*stack|top\s*only)", re.I)
_UPRIGHT_RE = re.compile(r"(不可倒置|正立|竖放|向上|箭头朝上|不可侧放|不可躺|upright|this\s*side\s*up)", re.I)
_LAYERS_RE = re.compile(r"(?:最多|限|不超过|max)\s*(?:堆|叠|码)?\s*(\d+)\s*(?:层|layers?)", re.I)
_ACCESSORY_RE = re.compile(r"(随主箱|同箱附带|混装在内|不单独占箱|含在主箱内)", re.I)


_FRAGILE_NAME_RE = re.compile(r"(易碎|fragile|玻璃)", re.I)


def normalize_placement_rules(req_text: Any, name_text: Any = "") -> Dict[str, Any]:
    """将摆放要求文本解析为结构化规则与展示标签。"""
    raw = normalize_text(req_text)
    name = normalize_text(name_text)
    combined = f"{raw} {name}".strip()

    rules: Dict[str, Any] = {
        "zone_preference": "ANY",
        "is_door_stopper": False,
        "allow_stacking_on_top": True,
        "upright_only": False,
        "must_be_on_floor": False,
    }
    tags: List[str] = []
    req_label = "放中间"
    is_acc = bool(_ACCESSORY_RE.search(combined))

    if not raw or is_placeholder(raw):
        if name and _FRAGILE_NAME_RE.search(name):
            rules["allow_stacking_on_top"] = False
            tags.append("易碎防压")
        return {
            "raw": "",
            "requirement": "放中间",
            "logistics_note": "",
            "placement_rules": rules,
            "rule_tags": tags,
            "is_accessory_note": is_acc,
        }

    if _DOOR_RE.search(raw):
        rules["zone_preference"] = "DOOR"
        rules["is_door_stopper"] = True
        tags.append("贴门/最后放")
        req_label = "封柜门"
    elif _REAR_RE.search(raw):
        rules["zone_preference"] = "REAR"
        tags.append("最里面/先装")
        req_label = "放最里面"

    if _FLOOR_RE.search(raw):
        rules["must_be_on_floor"] = True
        tags.append("底层落地")

    if _NO_STACK_RE.search(raw):
        rules["allow_stacking_on_top"] = False
        rules["max_stack_layers"] = 1
        tags.append("不可叠压")
    elif name and _FRAGILE_NAME_RE.search(name):
        rules["allow_stacking_on_top"] = False
        tags.append("易碎防压")

    if _UPRIGHT_RE.search(raw):
        rules["upright_only"] = True
        tags.append("正立向上")

    m_layers = _LAYERS_RE.search(raw)
    if m_layers:
        max_l = max(1, int(m_layers.group(1)))
        rules["max_stack_layers"] = max_l
        tags.append(f"限堆{max_l}层")

    is_acc = bool(_ACCESSORY_RE.search(combined))

    return {
        "raw": raw,
        "requirement": req_label if tags else "放中间",
        "logistics_note": "" if tags else raw,
        "placement_rules": rules,
        "rule_tags": tags,
        "is_accessory_note": is_acc,
    }
