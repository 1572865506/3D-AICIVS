"""
3D-AICIVS 测试用例生成器

用途：基于 SKU 原型和约束组合矩阵，批量生成固定/随机/变异测试用例。
输出：JSON 用例文件写入 tests/cases/generated/ 或 tests/cases/random/

生成模式：
  - fixed:  基于 phase1_matrix 正交矩阵生成确定性用例
  - random: 受控随机化（固定 seed 可复现）
  - mutate: 对现有用例做微扰（尺寸±3-8%、数量×1.2-1.8、约束翻转）

被调用方：scripts/test_harness/runner.py, 命令行直接调用
"""

import os
import sys
import json
import copy
import random
import argparse
from typing import Dict, List, Any, Optional, Tuple

# 确保 UTF-8 输出（Windows 兼容）
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 项目根目录
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "scripts", "test_harness", "templates")


def _load_json(filepath: str) -> Any:
    """加载 JSON 文件"""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(data: Any, filepath: str):
    """保存 JSON 文件（自动创建目录）"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


class CaseGenerator:
    """测试用例生成器：支持固定模板、受控随机、对抗性变异三种模式"""

    def __init__(self):
        """初始化：加载模板文件"""
        self.container_specs: Dict = _load_json(os.path.join(TEMPLATES_DIR, "container_specs.json"))
        raw_archetypes = _load_json(os.path.join(TEMPLATES_DIR, "sku_archetypes.json"))
        # 将列表转为以 id 为键的字典，方便按 id 查找
        self.archetypes: Dict[str, Dict] = {}
        for arch in raw_archetypes.get("archetypes", []):
            self.archetypes[arch["id"]] = arch
        self.combos: Dict = _load_json(os.path.join(TEMPLATES_DIR, "constraint_combos.json"))

    def _sample_range(self, lo: float, hi: float, rng: random.Random) -> float:
        """在 [lo, hi] 范围内均匀采样"""
        return round(rng.uniform(lo, hi), 3)

    def _sample_int_range(self, lo: int, hi: int, rng: random.Random) -> int:
        """在 [lo, hi] 范围内均匀采样整数"""
        return rng.randint(lo, hi)

    def _pick_archetypes_for_scenario(
        self, scenario: str, constraint_level: str, rigid_ratio_key: str,
        hetero_key: str, rng: random.Random
    ) -> List[str]:
        """根据场景和配置选择 SKU 原型 ID 列表"""
        hetero_map = {"UNIFORM": 1, "LOW": 3, "MEDIUM": 6, "HIGH": 12, "EXTREME": 18}
        target_count = hetero_map.get(hetero_key, 6)

        # 场景决定必选原型
        must_include: List[str] = []
        if scenario == "DOOR_HEAVY":
            must_include = ["DOOR_SEAL_PANEL", "ELASTIC_DOOR_FILLER"]
        elif scenario == "TIPPING_RISK":
            must_include = ["TALL_SLENDER", "HEAVY_BASE"]
        elif scenario == "OVERWEIGHT":
            must_include = ["HEAVY_BASE", "PALLET_UNIT"]
        elif scenario == "EXTREME_RATIO":
            must_include = ["LONG_BAR", "FLAT_PANEL", "TV_LARGE"]

        # 刚性/弹性配比决定可选池
        ratio_cfg = self.combos.get("rigid_ratios", {}).get(rigid_ratio_key, {})
        elastic_pct = ratio_cfg.get("elastic_pct", 0.2)
        rigid_pool = [k for k, v in self.archetypes.items()
                      if not v.get("default_constraints", {}).get("isElastic", False)]
        elastic_pool = [k for k, v in self.archetypes.items()
                        if v.get("default_constraints", {}).get("isElastic", False)]

        # 确保必选项在最终列表中
        selected = list(must_include)
        remaining_count = max(0, target_count - len(selected))

        # 按比例分配刚性和弹性
        n_elastic = max(0, int(remaining_count * elastic_pct))
        n_rigid = remaining_count - n_elastic

        avail_rigid = [k for k in rigid_pool if k not in selected]
        avail_elastic = [k for k in elastic_pool if k not in selected]

        if n_rigid > 0 and avail_rigid:
            selected.extend(rng.sample(avail_rigid, min(n_rigid, len(avail_rigid))))
        if n_elastic > 0 and avail_elastic:
            selected.extend(rng.sample(avail_elastic, min(n_elastic, len(avail_elastic))))

        return selected[:target_count] if len(selected) > target_count else selected

    def _make_sku(self, arch_id: str, sku_idx: int, rng: random.Random,
                  constraint_level: str) -> Dict[str, Any]:
        """从原型生成一个具体的 SKU 货物条目"""
        arch = self.archetypes[arch_id]
        sku = {
            "sku": f"SKU-{sku_idx:03d}",
            "name": f"{arch['name']}-{rng.randint(100, 999)}",
            "w": self._sample_range(arch["w"][0], arch["w"][1], rng),
            "d": self._sample_range(arch["d"][0], arch["d"][1], rng),
            "h": self._sample_range(arch["h"][0], arch["h"][1], rng),
            "weight": round(self._sample_range(arch["weight"][0], arch["weight"][1], rng), 1),
            "quantity": self._sample_int_range(arch["typical_qty"][0], arch["typical_qty"][1], rng),
        }
        # 复制原型默认约束
        for k, v in arch.get("default_constraints", {}).items():
            sku[k] = copy.deepcopy(v)

        # 根据约束级别添加额外约束
        active = self.combos.get("constraint_levels", {}).get(constraint_level, {}).get("active_constraints", [])
        if "max_stack_layers" in active and "max_stack_layers" not in sku:
            sku["max_stack_layers"] = rng.choice([2, 3, 4])
        if "max_bearing" in active and "maxBearingKg" not in sku:
            sku["maxBearingKg"] = round(rng.uniform(10, 80), 1)
        if "must_be_on_floor" in active and rng.random() > 0.7:
            sku["mustBeOnFloor"] = True
        if "no_top_stack" in active and rng.random() > 0.7:
            sku["allowStackingOnTop"] = False

        return sku

    def _get_container(self, container_type: str) -> Dict:
        """获取集装箱规格（兼容模板顶层无包装的结构）"""
        spec = self.container_specs.get(container_type, self.container_specs.get("40HQ", {}))
        return {
            "usable": spec["usable"],
            "maxPayloadTons": spec.get("maxPayloadTons", 26.5)
        }

    # ═══════════════════════ 固定模板生成 ═══════════════════════

    def generate_fixed(self, output_dir: str, dry_run: bool = False) -> int:
        """基于 phase1_matrix 生成固定用例，返回生成数量"""
        matrix = self.combos.get("phase1_matrix", [])
        generated = 0

        for idx, entry in enumerate(matrix):
            container_type = entry.get("container", "40HQ")
            constraint = entry.get("constraint", "NONE")
            rigid_ratio = entry.get("rigid_ratio", "DOMINANT_RIGID")
            hetero = entry.get("heterogeneity", "MEDIUM")
            scenario = entry.get("scenario", "NORMAL")
            count = entry.get("count", 1)

            for i in range(count):
                case_id = f"GEN-P1-{idx+1:02d}-{i+1:02d}"
                rng = random.Random(f"{case_id}-fixed-{idx}-{i}")

                arch_ids = self._pick_archetypes_for_scenario(
                    scenario, constraint, rigid_ratio, hetero, rng)

                cargo = []
                for j, arch_id in enumerate(arch_ids):
                    sku = self._make_sku(arch_id, j + 1, rng, constraint)
                    cargo.append(sku)

                case_name_parts = {
                    "NONE": "无约束", "LIGHT": "轻约束", "MEDIUM": "中约束", "HEAVY": "全约束"
                }
                case_data = {
                    "case_id": case_id,
                    "case_name": f"自动生成: {container_type}-{case_name_parts.get(constraint, constraint)}-{scenario}",
                    "description": f"Auto-generated: container={container_type}, constraint={constraint}, "
                                   f"rigid={rigid_ratio}, hetero={hetero}, scenario={scenario}",
                    "tags": [container_type, constraint, rigid_ratio, hetero, scenario, "GENERATED"],
                    "container": self._get_container(container_type),
                    "cargo": cargo
                }

                filepath = os.path.join(output_dir, f"{case_id}.json")
                if dry_run:
                    print(f"[DRY-RUN] 将创建: {filepath} ({len(cargo)} SKU)")
                else:
                    _save_json(case_data, filepath)
                    print(f"[已创建] {filepath} ({len(cargo)} SKU)")
                generated += 1

        return generated

    # ═══════════════════════ 随机生成 ═══════════════════════

    def generate_random(self, output_dir: str, count: int, seed: int,
                        dry_run: bool = False) -> int:
        """受控随机生成用例，返回生成数量"""
        rng = random.Random(seed)
        container_types = list(self.container_specs.keys())
        constraint_levels = list(self.combos.get("constraint_levels", {}).keys())
        rigid_ratios = list(self.combos.get("rigid_ratios", {}).keys())
        hetero_levels = list(self.combos.get("size_heterogeneity", {}).keys())
        scenarios = list(self.combos.get("special_scenarios", {}).keys())

        for i in range(count):
            case_id = f"GEN-RAND-{seed}-{i+1:04d}"
            ct = rng.choice(container_types)
            cl = rng.choice(constraint_levels)
            rr = rng.choice(rigid_ratios)
            ht = rng.choice(hetero_levels)
            sc = rng.choice(scenarios)

            arch_ids = self._pick_archetypes_for_scenario(sc, cl, rr, ht, rng)
            cargo = [self._make_sku(aid, j + 1, rng, cl) for j, aid in enumerate(arch_ids)]

            case_data = {
                "case_id": case_id,
                "case_name": f"随机生成: {ct}-{cl}-{sc} (seed={seed})",
                "description": f"Random: container={ct}, constraint={cl}, rigid={rr}, "
                               f"hetero={ht}, scenario={sc}, seed={seed}",
                "tags": [ct, cl, rr, ht, sc, "RANDOM"],
                "container": self._get_container(ct),
                "cargo": cargo
            }

            filepath = os.path.join(output_dir, f"{case_id}.json")
            if dry_run:
                print(f"[DRY-RUN] 将创建: {filepath} ({len(cargo)} SKU)")
            else:
                _save_json(case_data, filepath)
                print(f"[已创建] {filepath} ({len(cargo)} SKU)")

        return count

    # ═══════════════════════ 对抗性变异 ═══════════════════════

    def mutate_case(self, source_file: str, output_dir: str, count: int,
                    dry_run: bool = False) -> int:
        """对现有用例做微扰变异，返回生成数量"""
        base = _load_json(source_file)
        base_id = base.get("case_id", "UNKNOWN")

        for i in range(count):
            rng = random.Random(f"{base_id}-mutate-{i}")
            mutated = copy.deepcopy(base)
            mutated["case_id"] = f"{base_id}-MUT-{i+1:02d}"
            mutated["case_name"] = f"{base.get('case_name', '')} (变异 #{i+1})"
            mutated["description"] = f"Mutated from {base_id}, variant {i+1}"
            mutated.setdefault("tags", []).append("MUTATED")

            for item in mutated.get("cargo", []):
                # 尺寸微扰 ±3~8%
                for dim in ("w", "d", "h"):
                    if dim in item:
                        factor = 1.0 + rng.choice([1, -1]) * rng.uniform(0.03, 0.08)
                        item[dim] = round(item[dim] * factor, 3)
                # 数量微扰 ×1.2~1.8
                if "quantity" in item:
                    item["quantity"] = max(1, int(item["quantity"] * rng.uniform(1.2, 1.8)))
                # 随机翻转一个布尔约束
                bools = [c for c in ("isElastic", "allowDoorZone", "mustBeOnFloor",
                         "allowStackingOnTop", "allowFlat", "allowSide") if c in item]
                if bools and rng.random() > 0.5:
                    key = rng.choice(bools)
                    item[key] = not item[key]

            filepath = os.path.join(output_dir, f"{mutated['case_id']}.json")
            if dry_run:
                print(f"[DRY-RUN] 将创建: {filepath}")
            else:
                _save_json(mutated, filepath)
                print(f"[已创建] {filepath}")

        return count


def main():
    parser = argparse.ArgumentParser(description="3D-AICIVS 测试用例生成器")
    parser.add_argument("--mode", choices=["fixed", "random", "mutate"], required=True,
                        help="生成模式: fixed(模板矩阵), random(受控随机), mutate(对抗变异)")
    parser.add_argument("--output", type=str, help="输出目录（默认按模式自动选择）")
    parser.add_argument("--count", type=int, default=50, help="随机/变异模式的生成数量")
    parser.add_argument("--seed", type=int, default=42, help="随机种子（仅 random 模式）")
    parser.add_argument("--source", type=str, help="源用例文件路径（仅 mutate 模式）")
    parser.add_argument("--dry-run", action="store_true", help="演练模式，不实际写入文件")
    args = parser.parse_args()

    output_dir = args.output
    if not output_dir:
        output_dir = os.path.join(PROJECT_ROOT, "tests", "cases",
                                  "random" if args.mode == "random" else "generated")
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(PROJECT_ROOT, output_dir)

    gen = CaseGenerator()

    if args.mode == "fixed":
        n = gen.generate_fixed(output_dir, args.dry_run)
        print(f"\n✅ 固定模板生成完成，共 {n} 个用例")
    elif args.mode == "random":
        n = gen.generate_random(output_dir, args.count, args.seed, args.dry_run)
        print(f"\n✅ 随机生成完成，共 {n} 个用例 (seed={args.seed})")
    elif args.mode == "mutate":
        if not args.source:
            print("❌ 错误: mutate 模式需要 --source 参数")
            sys.exit(1)
        source = args.source if os.path.isabs(args.source) else os.path.join(PROJECT_ROOT, args.source)
        n = gen.mutate_case(source, output_dir, args.count, args.dry_run)
        print(f"\n✅ 变异生成完成，共 {n} 个用例")


if __name__ == "__main__":
    main()
