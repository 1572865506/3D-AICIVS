"""生成虚拟货单（synthetic manifests），用于实装可用性模拟与自学习数据采集。

设计原则：
- 不是随机堆料，而是按 4 个业务原型 + 边界组合构建：
  3C/显示器（薄板+大箱）、家电/汽配重货、电商杂货多 SKU、托盘/单 SKU 大货；
  另加门区薄板、易碎、多站卸货、无封门件、20GP/45HQ、超重、限层/仅立放。
- 尺寸/重量从 `scripts/test_harness/templates/sku_archetypes.json` 的区间内
  按固定 seed 采样，保证可复现；数量为固定值，便于做验收基线。
- 输出 `tests/cases/virtual/*.json`，`meta.synthetic=true`，不冒充真实业务单。

运行：python scripts/generate_virtual_manifests.py
被谁调用：人工/CI 初始化虚拟测试集、自学习数据集构建。
"""

import json
import os
import random

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(PROJECT_ROOT, "scripts", "test_harness", "templates")
OUT_DIR = os.path.join(PROJECT_ROOT, "tests", "cases", "virtual")


def _load(name):
    with open(os.path.join(TEMPLATES, name), "r", encoding="utf-8") as f:
        return json.load(f)


ARCHETYPES = {a["id"]: a for a in _load("sku_archetypes.json")["archetypes"]}
CONTAINERS = _load("container_specs.json")


# 每个用例：id/name/desc/container/seed/items[(archetype, qty, extras)]
CASES = [
    {
        "id": "VIRTUAL-3C-MIX-40HQ",
        "name": "虚拟-3C 显示器混装（薄板封门+大箱）",
        "desc": "40HQ：电视/显示器/封门薄板/弹性填充，验证门区安全与墙缝",
        "container": "40HQ", "seed": 101, "target_ratio": 0.65,
        "items": [
            ("TV_LARGE", 50, {}),
            ("TV_MEDIUM", 120, {}),
            ("DISPLAY_SMALL", 180, {}),
            ("DOOR_SEAL_PANEL", 260, {"door": True}),
            ("ELASTIC_FILLER", 200, {"elastic": True}),
        ],
    },
    {
        "id": "VIRTUAL-3C-THIN-DOOR-40HQ",
        "name": "虚拟-3C 薄板门墙（高薄板封门）",
        "desc": "40HQ：大量薄板封门，验证门面 SF 与门端台阶",
        "container": "40HQ", "seed": 102, "target_ratio": 0.8, "time_budget_s": 60,
        "items": [
            ("DISPLAY_SMALL", 300, {}),
            ("FLAT_PANEL", 220, {}),
            ("DOOR_SEAL_PANEL", 300, {"door": True}),
            ("ELASTIC_DOOR_FILLER", 200, {"elastic": True}),
        ],
    },
    {
        "id": "VIRTUAL-APPLIANCE-HEAVY-40GP",
        "name": "虚拟-家电重货（重底座落地）",
        "desc": "40GP：重型底座必须落地 + 标准纸箱，验证承重/压强/重心",
        "container": "40GP", "seed": 201, "target_ratio": 0.55,
        "items": [
            ("HEAVY_BASE", 30, {"floor": True}),
            ("STANDARD_BOX", 180, {}),
            ("CUBE_BOX", 90, {}),
        ],
    },
    {
        "id": "VIRTUAL-AUTO-LONG-40HQ",
        "name": "虚拟-汽配长条箱（长宽比大）",
        "desc": "40HQ：长条形管箱 + 重底座 + 标准箱，验证长件摆放与支撑",
        "container": "40HQ", "seed": 202, "target_ratio": 0.6, "time_budget_s": 45,
        "known_issue": {
            "id": "AUTO-LONG-001",
            "owner": "solver",
            "review_by": "2026-12-15",
            "note": "长条箱+重底座：刚性件约 95% 未装完（长件摆放与支撑受限，待修）",
        },
        "items": [
            ("LONG_BAR", 70, {}),
            ("HEAVY_BASE", 20, {"floor": True}),
            ("STANDARD_BOX", 120, {}),
        ],
    },
    {
        "id": "VIRTUAL-ECOMMERCE-MIX-40HQ",
        "name": "虚拟-电商杂货（多 SKU 小件）",
        "desc": "40HQ：标准箱/小配件/立方箱/微箱混装，验证碎片化与同 SKU 聚集",
        "container": "40HQ", "seed": 301,
        "items": [
            ("STANDARD_BOX", 200, {}),
            ("SMALL_ACCESSORY", 400, {}),
            ("CUBE_BOX", 120, {}),
            ("MICRO_CUBE", 300, {}),
        ],
    },
    {
        "id": "VIRTUAL-PALLET-SINGLE-40HQ",
        "name": "虚拟-托盘单 SKU 大货",
        "desc": "40HQ：单一托盘货 350 件，验证装载率与稳定性",
        "container": "40HQ", "seed": 302, "target_ratio": None, "time_budget_s": 20,
        "floor_limited": True,
        "items": [("PALLET_UNIT", 24, {"floor": True})],
    },
    {
        "id": "VIRTUAL-FRAGILE-40HQ",
        "name": "虚拟-易碎仪器（禁止顶压）",
        "desc": "40HQ：易碎仪器不做承压面 + 标准箱 + 弹性填充",
        "container": "40HQ", "seed": 401,
        "items": [
            ("FRAGILE_INSTRUMENT", 60, {"fragile": True}),
            ("STANDARD_BOX", 150, {}),
            ("ELASTIC_FILLER", 120, {"elastic": True}),
        ],
    },
    {
        "id": "VIRTUAL-MULTISTOP-40HQ",
        "name": "虚拟-多点卸货（3 站）",
        "desc": "40HQ：第 1 站封门件靠门、2/3 站依次向内，验证站序与装载顺序",
        "container": "40HQ", "seed": 501, "time_budget_s": 60,
        "expected_error": ["DOOR_SEAL_CAPACITY_UNSATISFIABLE"],
        "items": [
            ("DOOR_SEAL_PANEL", 200, {"door": True, "stop": 1}),
            ("STANDARD_BOX", 150, {"stop": 2}),
            ("CUBE_BOX", 100, {"stop": 3}),
            ("ELASTIC_FILLER", 100, {"elastic": True}),
        ],
    },
    {
        "id": "VIRTUAL-NODOOR-40GP",
        "name": "虚拟-无封门件（通用货）",
        "desc": "40GP：无封柜门货物，验证无门区语义时的通用摆放",
        "container": "40GP", "seed": 502,
        "items": [
            ("STANDARD_BOX", 250, {}),
            ("CUBE_BOX", 100, {}),
            ("SMALL_ACCESSORY", 200, {}),
        ],
    },
    {
        "id": "VIRTUAL-20GP-DENSE",
        "name": "虚拟-20GP 高密度小件",
        "desc": "20GP：标准箱+小配件+微箱，验证小柜高密度装载",
        "container": "20GP", "seed": 601,
        "items": [
            ("STANDARD_BOX", 90, {}),
            ("SMALL_ACCESSORY", 180, {}),
            ("MICRO_CUBE", 150, {}),
        ],
    },
    {
        "id": "VIRTUAL-45HQ-LONG",
        "name": "虚拟-45HQ 长柜混装",
        "desc": "45HQ：长条箱+标准箱+立方箱，验证长柜纵深利用",
        "container": "45HQ", "seed": 602,
        "items": [
            ("LONG_BAR", 80, {}),
            ("STANDARD_BOX", 150, {}),
            ("CUBE_BOX", 80, {}),
        ],
    },
    {
        "id": "VIRTUAL-UPRIGHT-40HQ",
        "name": "虚拟-仅立放屏幕（朝向锁定）",
        "desc": "40HQ：屏幕仅允许立放 + 标准箱，验证朝向约束与混装",
        "container": "40HQ", "seed": 701, "target_ratio": 0.65,
        "items": [
            ("UPRIGHT_ONLY_SCREEN", 200, {"upright": True}),
            ("STANDARD_BOX", 120, {}),
        ],
    },
    {
        "id": "VIRTUAL-LIMITED-STACK-40HQ",
        "name": "虚拟-限层堆叠（最多 2 层）",
        "desc": "40HQ：限层箱 + 零承压板 + 标准箱，验证层数约束与顶面利用",
        "container": "40HQ", "seed": 702, "target_ratio": 0.35, "time_budget_s": 30,
        "items": [
            ("LIMITED_STACK_BOX", 200, {"max_layers": 2}),
            ("ZERO_BEARING_SLAB", 50, {"no_top_stack": True}),
            ("STANDARD_BOX", 100, {}),
        ],
    },
    {
        "id": "VIRTUAL-OVERWEIGHT-40HQ",
        "name": "虚拟-超重货单（载重受限）",
        "desc": "40HQ：重底座数量超过柜体载重，验收应给出载重受限而非静默弃装",
        "container": "40HQ", "seed": 801, "target_ratio": None, "time_budget_s": 20,
        "items": [
            ("HEAVY_BASE", 80, {"floor": True, "heavy": True}),
            ("STANDARD_BOX", 100, {}),
        ],
        "expected_reject": ["DG-003", "DG-005"],
    },
    {
        "id": "VIRTUAL-MULTISTOP-4STOP-40HQ",
        "name": "虚拟-四点卸货（4 站 + 封门件）",
        "desc": "40HQ：4 站配送，第 1 站封门件靠门，验证区段分配与容量",
        "container": "40HQ", "seed": 901, "target_ratio": 0.65, "time_budget_s": 60,
        "expected_error": ["DOOR_SEAL_CAPACITY_UNSATISFIABLE"],
        "known_issue": {"id": "DOOR-STEP-CAPACITY-001", "owner": "solver", "review_by": "2026-12-15", "note": "封门薄板在门端台阶下有效容量不足：171 件仅 44 件可放，需门面政策/容量预检"},
        "items": [
            ("DOOR_SEAL_PANEL", 80, {"door": True, "stop": 1}),
            ("STANDARD_BOX", 120, {"stop": 2}),
            ("CUBE_BOX", 100, {"stop": 3}),
            ("SMALL_ACCESSORY", 180, {"stop": 4}),
            ("ELASTIC_FILLER", 100, {"elastic": True, "stop": 4}),
        ],
    },
    {
        "id": "VIRTUAL-ECOMMERCE-MULTISTOP-40HQ",
        "name": "虚拟-电商多站（3 站无封门件）",
        "desc": "40HQ：多 SKU 小件 3 站配送，无封门件，验证区段与碎片化",
        "container": "40HQ", "seed": 902, "target_ratio": 0.7, "time_budget_s": 45,
        "items": [
            ("STANDARD_BOX", 200, {"stop": 1}),
            ("SMALL_ACCESSORY", 300, {"stop": 2}),
            ("CUBE_BOX", 120, {"stop": 3}),
            ("MICRO_CUBE", 200, {"stop": 3}),
        ],
    },
    {
        "id": "VIRTUAL-PALLET-MIXED-40HQ",
        "name": "虚拟-托盘混装（落地+纸箱）",
        "desc": "40HQ：托盘仅落地 + 标准纸箱/立方箱混装，验证地板竞争",
        "container": "40HQ", "seed": 903, "target_ratio": 0.6, "time_budget_s": 45,
        "items": [
            ("PALLET_UNIT", 14, {"floor": True}),
            ("STANDARD_BOX", 120, {}),
            ("CUBE_BOX", 60, {}),
        ],
    },
    {
        "id": "VIRTUAL-THIN-DOOR-HIGHFILL-40HQ",
        "name": "虚拟-薄板高填充门区",
        "desc": "40HQ：薄板/显示器 85% 填充 + 封门薄板，验证门区安全与墙缝",
        "container": "40HQ", "seed": 904, "target_ratio": 0.85, "time_budget_s": 60,
        "expected_error": ["DOOR_SEAL_CAPACITY_UNSATISFIABLE"],
        "known_issue": {"id": "DOOR-STEP-BAND-001", "owner": "solver", "review_by": "2026-12-15", "note": "高填充时门面薄板 SF<1.5：0.25m 门端台阶覆盖不到 0.56m 厚封门墙，待门面政策决策"},
        "items": [
            ("DISPLAY_SMALL", 500, {}),
            ("FLAT_PANEL", 400, {}),
            ("DOOR_SEAL_PANEL", 260, {"door": True}),
            ("ELASTIC_DOOR_FILLER", 150, {"elastic": True}),
        ],
    },
    {
        "id": "VIRTUAL-NODOOR-HIGHFILL-40HQ",
        "name": "虚拟-无门高密度（多 SKU）",
        "desc": "40HQ：无封门件的高密度多 SKU 货单，验证无门区语义下的装载率",
        "container": "40HQ", "seed": 905, "target_ratio": 0.75, "time_budget_s": 45,
        "known_issue": {"id": "MIXED-HIGHFILL-STARVE-001", "owner": "solver", "review_by": "2026-12-15", "note": "高密度混装下 CUBE_BOX 0 放置（墙型/回填未覆盖），待修"},
        "items": [
            ("STANDARD_BOX", 400, {}),
            ("CUBE_BOX", 200, {}),
            ("SMALL_ACCESSORY", 500, {}),
            ("MICRO_CUBE", 400, {}),
        ],
    },
]


def _sample(value_range, rng):
    lo, hi = value_range
    if isinstance(lo, int) and isinstance(hi, int):
        return rng.randint(lo, hi)
    return round(rng.uniform(float(lo), float(hi)), 3)


def _build_cargo(items, rng):
    cargo = []
    for idx, (arch_id, qty, extras) in enumerate(items, 1):
        arch = ARCHETYPES[arch_id]
        w = _sample(arch["w"], rng)
        d = _sample(arch["d"], rng)
        h = _sample(arch["h"], rng)
        weight = round(rng.uniform(*[float(v) for v in arch["weight"]]), 2)
        sku = f"V{idx:02d}-{arch_id}"
        req = "放中间"
        entry = {
            "sku": sku, "name": arch["name"], "w": w, "d": d, "h": h,
            "weight": weight, "quantity": int(qty), "requirement": req,
        }
        if extras.get("door"):
            entry["requirement"] = "封柜门"
            entry["allowDoorZone"] = True
        if extras.get("elastic"):
            entry["requirement"] = "顶部填平,按需调节"
            entry["isElastic"] = True
        if extras.get("floor"):
            entry["requirement"] = "重货,必须落地"
            entry["mustBeOnFloor"] = True
        if extras.get("fragile"):
            entry["requirement"] = "易碎,不可压"
            entry["allowStackingOnTop"] = False
        if extras.get("upright"):
            entry["allowedOrientation"] = "upright"
        if extras.get("max_layers"):
            entry["max_stack_layers"] = int(extras["max_layers"])
        if extras.get("no_top_stack"):
            entry["allowStackingOnTop"] = False
        if extras.get("stop"):
            entry["unloadStop"] = int(extras["stop"])
        cargo.append(entry)
    return cargo


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    written = []
    for spec in CASES:
        rng = random.Random(spec["seed"])
        container = CONTAINERS[spec["container"]]
        cargo = _build_cargo(spec["items"], rng)
        # 按目标体积比缩放数量，让货单接近真实装载率（而不是稀疏堆料）
        target_ratio = spec.get("target_ratio", 0.7)
        if target_ratio:
            usable = container["usable"]
            container_vol = usable["L"] * usable["W"] * usable["H"]
            current_vol = sum(i["w"] * i["d"] * i["h"] * i["quantity"] for i in cargo)
            if current_vol > 0:
                factor = max(0.2, target_ratio * container_vol / current_vol)
                for item in cargo:
                    item["quantity"] = max(1, int(round(item["quantity"] * factor)))
        if spec.get("floor_limited"):
            # 仅落地件不能用体积比反推数量，按地面面积上限收敛（85% 地板利用率）
            usable = container["usable"]
            for item in cargo:
                cap = int(0.85 * usable["L"] * usable["W"] / max(1e-6, item["w"] * item["d"]))
                item["quantity"] = max(1, min(item["quantity"], cap))
        # 混合货单里"必须落地"的 SKU 同样受地面面积约束，否则物理上不可行
        usable = container["usable"]
        for item in cargo:
            if item.get("mustBeOnFloor"):
                cap = int(0.80 * usable["L"] * usable["W"] / max(1e-6, item["w"] * item["d"]))
                item["quantity"] = max(1, min(item["quantity"], cap))
        case = {
            "case_id": spec["id"],
            "case_name": spec["name"],
            "description": spec["desc"],
            "meta": {
                "synthetic": True,
                "archetype": spec["id"].split("-")[1].lower(),
                "seed": spec["seed"],
                "container": spec["container"],
                "target_volume_ratio": target_ratio,
                "time_budget_s": spec.get("time_budget_s", 45),
                "floor_limited": bool(spec.get("floor_limited", False)),
                "known_issue": spec.get("known_issue"),
                "expected_reject": spec.get("expected_reject", []),
                "expected_error": spec.get("expected_error", []),
            },
            "container": {
                "usable": container["usable"],
                "maxPayloadTons": container["maxPayloadTons"],
            },
            "cargo": cargo,
        }
        path = os.path.join(OUT_DIR, f"{spec['id'].lower().replace('-', '_')}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(case, f, ensure_ascii=False, indent=2)
        written.append(path)
    print(f"Virtual manifests written: {len(written)} -> {OUT_DIR}")


if __name__ == "__main__":
    main()
