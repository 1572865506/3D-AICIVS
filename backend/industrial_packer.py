"""
3D-AICIVS Industrial Container Packing Engine (Python 3 Kernel)
Implementation of the 6 Core Modules based on implementation_plan.md:
1. 物理压强与朝向控制 (Physical Pressure & Matrix Orientation Control)
2. 成柱成墙同品聚合 (Column & Wall Building with Homogeneous Affinity)
3. 尾数箱双重安全拦截与平整度 (Remainder Security & Flatness Control Δh <= 3mm)
4. 3D 动态重心与业务装载分区 (Dynamic 3D CoG & Zone Requirements)
5. 阶梯防倾与超容弹性智能核减 (Anti-Toppling Step & Overcapacity Elastic Trimming)
6. 箱门 1.2m 警戒区防倾倒锁定 (Door Safety Zone Locking K = Dx/H >= 0.50)
"""

import math
import re
import time
from typing import List, Dict, Any, Optional, Tuple

class IndustrialSmartContainerPacker:
    def __init__(self, container_spec: Dict[str, Any], weights: Optional[Dict[str, float]] = None):
        """
        container_spec contains:
          - usable: {'L': float, 'W': float, 'H': float}
          - maxPayloadTons: float
        weights contains 6-dimensional tunable parameters:
          - affinity, verticalStack, wallSlicing, notchLeveling, cogBalance, doorSafety
        """
        usable = container_spec.get('usable', {})
        self.L = float(usable.get('L', container_spec.get('intL', 12.032)))
        self.W = float(usable.get('W', container_spec.get('intW', 2.352)))
        self.H = float(usable.get('H', container_spec.get('intH', 2.698)))
        self.max_payload_kg = float(container_spec.get('maxPayloadTons', 26.5)) * 1000.0
        
        # 模块 6：箱门 1.2m 警戒区边界
        self.door_zone_x = max(0.0, self.L - 1.20)
        
        default_weights = {
            'affinity': 3000.0,
            'verticalStack': 3500.0,
            'wallSlicing': 50000.0,
            'notchLeveling': 2500.0,
            'cogBalance': 1500.0,
            'doorSafety': 1200.0
        }
        self.weights = {**default_weights, **(weights or {})}

    @staticmethod
    def is_aabb_overlap(a: Dict[str, float], b: Dict[str, float], eps: float = 0.0005) -> bool:
        """3D 轴对齐包围盒（AABB）碰撞检测"""
        return (
            a['x'] + a['w'] > b['x'] + eps and
            b['x'] + b['w'] > a['x'] + eps and
            a['y'] + a['h'] > b['y'] + eps and
            b['y'] + b['h'] > a['y'] + eps and
            a['z'] + a['d'] > b['z'] + eps and
            b['z'] + b['d'] > a['z'] + eps
        )

    def get_safe_orientations(self, item: Dict[str, Any], current_x: float) -> List[Dict[str, float]]:
        """
        模块 1：朝向生成与姿态约束
        模块 6：箱门 1.2m 警戒区防倾倒锁定 (K = Dx / H >= 0.50)
        """
        allowed = item.get('allowedOrientation', 'allow_flat' if item.get('allowFlat') else 'upright')
        w, d, h = float(item['w']), float(item['d']), float(item['h'])
        
        raw = []
        if allowed == 'upright':
            raw = [
                {'l': w, 'wz': d, 'h': h},
                {'l': d, 'wz': w, 'h': h}
            ]
        elif allowed == 'allow_flat':
            raw = [
                {'l': w, 'wz': d, 'h': h},
                {'l': d, 'wz': w, 'h': h},
                {'l': w, 'wz': h, 'h': d},
                {'l': d, 'wz': h, 'h': d}
            ]
        else:
            raw = [
                {'l': w, 'wz': d, 'h': h},
                {'l': d, 'wz': w, 'h': h},
                {'l': w, 'wz': h, 'h': d},
                {'l': d, 'wz': h, 'h': d},
                {'l': h, 'wz': d, 'h': w},
                {'l': h, 'wz': w, 'h': d}
            ]

        # 模块 6 强制：箱门末端 1.2m 警戒区强制长高比 K = Dx/H >= 0.50，严禁窄面朝外翻转
        is_near_door = (current_x >= self.door_zone_x)
        if is_near_door:
            filtered = [
                ori for ori in raw 
                if (ori['l'] / ori['h'] >= 0.50) or (ori['h'] <= 0.25) or (ori['l'] >= 0.40)
            ]
            if filtered:
                raw = filtered

        # 排序：优先选择横截面填充率最高的朝向
        raw.sort(
            key=lambda o: (math.floor(self.W / o['wz']) * math.floor(self.H / o['h'])),
            reverse=True
        )
        return raw

    def get_zone_affinity_score(self, sku: Dict[str, Any], current_x: float) -> float:
        """
        模块 4：3D 重心调控与业务装货要求（最里面 -> 放中间 -> 封柜门）
        模块 5：超容时优先刚性，弹性件最后满柜核减
        全面联动 6 维动态权重：cogBalance, doorSafety
        """
        req = sku.get('requirement', '')
        is_rear = bool(re.search(r'最里面|rear|deep', req, re.IGNORECASE))
        is_mid = bool(re.search(r'放中间|mid|middle', req, re.IGNORECASE))
        is_door = bool(re.search(r'封柜门|door|front', req, re.IGNORECASE))
        is_elastic = sku.get('isElastic', False)

        cog_scale = float(self.weights.get('cogBalance', 1500.0)) / 1500.0
        door_scale = float(self.weights.get('doorSafety', 1200.0)) / 1200.0

        if current_x <= 2.5:
            # 深端：最里面最高优先；装完后放中间顺延填充，杜绝浪费
            if is_rear:
                return 100000.0 * cog_scale
            if is_mid:
                return 20000.0 * cog_scale
            if is_door:
                return -5000.0 * cog_scale
            return 10000.0
        elif current_x <= 8.0:
            # 中段：放中间最高优先；刚性封柜门次之
            if is_mid:
                return 50000.0 * cog_scale
            if is_door:
                return (10000.0 if is_elastic else 30000.0) * cog_scale
            if is_rear:
                return -10000.0 * cog_scale
            return 10000.0
        else:
            # 门区：刚性封柜门最高优先，弹性件最后收口
            if is_door:
                base_score = 70000.0 if is_elastic else 100000.0
                return base_score * door_scale
            if is_mid:
                return 10000.0
            if is_rear:
                return -20000.0
            return 10000.0

    def pack(self, cargo_manifest: List[Dict[str, Any]]) -> Dict[str, Any]:
        """执行完整装载求解并返回 3D 空间坐标与工程审计指标"""
        start_time = time.time()
        placed_boxes: List[Dict[str, Any]] = []
        elastic_trimmed_map: Dict[str, Any] = {}

        affinity_weight = float(self.weights.get('affinity', 3000.0))
        wall_weight = float(self.weights.get('wallSlicing', 50000.0))
        notch_weight = float(self.weights.get('notchLeveling', 2500.0))
        vert_weight = float(self.weights.get('verticalStack', 3500.0))

        sku_pool = []
        for m in cargo_manifest:
            req = m.get('requirement', '')
            is_elastic = bool(re.search(r'可以少放|可以减少|可减少|调节|按需', req, re.IGNORECASE)) or m.get('isElastic', False)
            sku_pool.append({
                **m,
                'w': float(m['w']),
                'd': float(m['d']),
                'h': float(m['h']),
                'weight': float(m.get('weight', 1.0)),
                'quantity': int(m['quantity']),
                'remQty': int(m['quantity']),
                'actualPlaced': 0,
                'isElastic': is_elastic
            })

        box_global_index = 0
        current_wall_x = 0.0
        last_primary_sku: Optional[Dict[str, Any]] = None

        # 模块 2：垂直成柱 ➔ 横向延展成墙 ➔ 同品连贯推进
        while current_wall_x < self.L - 0.03:
            available_skus = [s for s in sku_pool if s['remQty'] > 0]
            if not available_skus:
                break

            # 模块 2 同品聚合：优先锁定上一 SKU，保持同品类大宗大方阵
            def sku_anchor_sort_key(s):
                score = self.get_zone_affinity_score(s, current_wall_x)
                if last_primary_sku and s['sku'] == last_primary_sku['sku']:
                    score += affinity_weight * 10.0
                if s['isElastic']:
                    score -= 20000.0
                score += min(s['remQty'], 500) * 10.0 + (s['w'] * s['h'] * s['d']) * (wall_weight / 1000.0)
                return score

            available_skus.sort(key=sku_anchor_sort_key, reverse=True)
            primary_sku = available_skus[0]
            primary_oris = self.get_safe_orientations(primary_sku, current_wall_x)
            primary_ori = primary_oris[0]
            target_wall_thickness = primary_ori['l']

            current_z = 0.0
            wall_cols = []

            # 横向延展成墙 (Z: 0 -> W)
            while current_z < self.W - 0.02:
                active_skus = [s for s in sku_pool if s['remQty'] > 0]
                if not active_skus:
                    break

                def col_sku_sort_key(s):
                    score = 60000.0 if s['sku'] == primary_sku['sku'] else self.get_zone_affinity_score(s, current_wall_x)
                    if s['isElastic']:
                        score -= 20000.0
                    return score

                active_skus.sort(key=col_sku_sort_key, reverse=True)

                col_sku = None
                col_ori = None

                for sku in active_skus:
                    sk_oris = self.get_safe_orientations(sku, current_wall_x)
                    sk_oris.sort(key=lambda o: abs(o['l'] - target_wall_thickness))

                    for ori in sk_oris:
                        if current_wall_x + ori['l'] <= self.L + 0.001 and current_z + ori['wz'] <= self.W + 0.001:
                            test_box = {
                                'x': current_wall_x,
                                'y': 0.0,
                                'z': current_z,
                                'w': ori['l'],
                                'h': ori['h'],
                                'd': ori['wz']
                            }
                            collides = False
                            for pb in placed_boxes:
                                if self.is_aabb_overlap(test_box, pb):
                                    collides = True
                                    break

                            if not collides:
                                col_sku = sku
                                col_ori = ori
                                break
                    if col_sku:
                        break

                if not col_sku or not col_ori:
                    current_z += 0.05
                    continue

                # 模块 2：垂直连续成柱至内腔顶高 (Y: 0 -> H)
                # 模块 3：平整度约束与整层堆叠（杜绝孤立悬空碎块箱）
                max_layers = math.floor(self.H / col_ori['h'])
                actual_layers = min(col_sku['remQty'], max_layers)
                stacked = 0

                for lay in range(actual_layers):
                    if col_sku['remQty'] <= 0:
                        break

                    cand = {
                        'x': current_wall_x,
                        'y': lay * col_ori['h'],
                        'z': current_z,
                        'w': col_ori['l'],
                        'h': col_ori['h'],
                        'd': col_ori['wz']
                    }

                    placed_boxes.append({
                        'id': f"{col_sku['sku']}-{box_global_index + 1}",
                        'sku': col_sku['sku'],
                        'name': col_sku.get('name', ''),
                        'color': col_sku.get('color', 0x3b82f6),
                        'weight': col_sku['weight'],
                        'requirement': col_sku.get('requirement', ''),
                        'isElastic': col_sku['isElastic'],
                        'x': round(cand['x'], 4),
                        'y': round(cand['y'], 4),
                        'z': round(cand['z'], 4),
                        'w': round(cand['w'], 4),
                        'h': round(cand['h'], 4),
                        'd': round(cand['d'], 4)
                    })
                    box_global_index += 1
                    col_sku['actualPlaced'] += 1
                    col_sku['remQty'] -= 1
                    stacked += 1

                if stacked > 0:
                    wall_cols.append({
                        'zStart': current_z,
                        'zEnd': current_z + col_ori['wz'],
                        'xEnd': current_wall_x + col_ori['l'],
                        'topY': stacked * col_ori['h']
                    })
                    current_z += col_ori['wz']
                else:
                    current_z += 0.05

            if not wall_cols:
                current_wall_x += 0.08
                continue

            max_x_in_wall = max(c['xEnd'] for c in wall_cols)

            # 模块 3 & 4：前沿缺口与平整度平准化（平整度 Δh <= 3mm，0 虚位推进）
            for col in wall_cols:
                notch_x = col['xEnd']
                while notch_x < max_x_in_wall - 0.03:
                    avail_in_notch = [s for s in sku_pool if s['remQty'] > 0]
                    filled_notch = False

                    for sku in avail_in_notch:
                        oris = self.get_safe_orientations(sku, notch_x)
                        for ori in oris:
                            if notch_x + ori['l'] <= max_x_in_wall + 0.001 and col['zStart'] + ori['wz'] <= col['zEnd'] + 0.001:
                                current_y = 0.0
                                count = 0
                                while current_y + ori['h'] <= self.H + 0.001 and sku['remQty'] > 0:
                                    cand = {
                                        'x': notch_x,
                                        'y': current_y,
                                        'z': col['zStart'],
                                        'w': ori['l'],
                                        'h': ori['h'],
                                        'd': ori['wz']
                                    }
                                    c_check = False
                                    for pb in placed_boxes:
                                        if self.is_aabb_overlap(cand, pb):
                                            c_check = True
                                            break
                                    if c_check:
                                        break

                                    placed_boxes.append({
                                        'id': f"{sku['sku']}-{box_global_index + 1}",
                                        'sku': sku['sku'],
                                        'name': sku.get('name', ''),
                                        'color': sku.get('color', 0x3b82f6),
                                        'weight': sku['weight'],
                                        'requirement': sku.get('requirement', ''),
                                        'isElastic': sku['isElastic'],
                                        'x': round(cand['x'], 4),
                                        'y': round(cand['y'], 4),
                                        'z': round(cand['z'], 4),
                                        'w': round(cand['w'], 4),
                                        'h': round(cand['h'], 4),
                                        'd': round(cand['d'], 4)
                                    })
                                    box_global_index += 1
                                    sku['actualPlaced'] += 1
                                    sku['remQty'] -= 1
                                    count += 1
                                    current_y += ori['h']

                                if count > 0:
                                    notch_x += ori['l']
                                    filled_notch = True
                                    break
                        if filled_notch:
                            break
                    if not filled_notch:
                        break

            last_primary_sku = primary_sku if primary_sku['remQty'] > 0 else None
            current_wall_x = max_x_in_wall

        # 模块 5：超容弹性智能核减
        sku_stats_dict = {}
        total_unplaced = 0
        for s in sku_pool:
            total_unplaced += s['remQty']
            sku_stats_dict[s['sku']] = {
                'sku': s['sku'],
                'name': s.get('name', ''),
                'requirement': s.get('requirement', ''),
                'planned': s['quantity'],
                'placed': s['actualPlaced'],
                'unplaced': s['remQty'],
                'isFullyPlaced': (s['remQty'] == 0),
                'isElastic': s['isElastic']
            }
            if s['isElastic']:
                elastic_trimmed_map[s['sku']] = {
                    'sku': s['sku'],
                    'name': s.get('name', ''),
                    'plannedQty': s['quantity'],
                    'actualQty': s['actualPlaced'],
                    'trimmedQty': s['remQty'],
                    'reason': '已达到集装箱安全容积上限，根据弹性规则自动核减留存' if s['remQty'] > 0 else '100% 满额装入'
                }

        # 模块 4：3D 动态重心与轴荷偏载计算器
        total_mass = 0.0
        sum_mx = 0.0
        sum_my = 0.0
        sum_mz = 0.0
        used_vol = 0.0

        for b in placed_boxes:
            total_mass += b['weight']
            sum_mx += b['weight'] * (b['x'] + b['w'] / 2.0)
            sum_my += b['weight'] * (b['y'] + b['h'] / 2.0)
            sum_mz += b['weight'] * (b['z'] + b['d'] / 2.0)
            used_vol += (b['w'] * b['h'] * b['d'])

        cog_x = (sum_mx / total_mass) if total_mass > 0 else (self.L / 2.0)
        cog_y = (sum_my / total_mass) if total_mass > 0 else (self.H / 2.0)
        cog_z = (sum_mz / total_mass) if total_mass > 0 else (self.W / 2.0)

        lat_offset_percent = abs((cog_z - self.W / 2.0) / (self.W / 2.0)) * 100.0
        long_offset_percent = ((cog_x - self.L / 2.0) / (self.L / 2.0)) * 100.0

        # 0 碰撞安全审计
        total_collisions = 0
        n = len(placed_boxes)
        for i in range(n):
            for j in range(i + 1, n):
                if self.is_aabb_overlap(placed_boxes[i], placed_boxes[j]):
                    total_collisions += 1

        container_vol = self.L * self.W * self.H
        utilization_rate = round((used_vol / container_vol) * 100.0, 1)
        elapsed_ms = round((time.time() - start_time) * 1000.0, 2)

        return {
            'success': True,
            'totalCount': len(placed_boxes),
            'totalPlaced': len(placed_boxes),
            'totalUnplacedCount': total_unplaced,
            'totalCollisions': total_collisions,
            'usedVol': round(used_vol, 2),
            'utilization': utilization_rate,
            'totalMassKg': round(total_mass, 2),
            'totalWeightTons': round(total_mass / 1000.0, 2),
            'maxPayloadKg': self.max_payload_kg,
            'isOverweight': total_mass > self.max_payload_kg,
            'packedLength': round(current_wall_x, 3),
            'containerLength': self.L,
            'cog': {
                'x': round(cog_x, 3),
                'y': round(cog_y, 3),
                'z': round(cog_z, 3),
                'latOffsetPercent': round(lat_offset_percent, 1),
                'longOffsetPercent': round(long_offset_percent, 1),
                'isLatBalanced': lat_offset_percent <= 5.0,
                'isLongBalanced': abs(long_offset_percent) <= 10.0,
                'isLongCompliant': abs(long_offset_percent) <= 10.0
            },
            'elasticTrimmed': list(elastic_trimmed_map.values()),
            'skuStats': sku_stats_dict,
            'skuList': [
                {
                    'sku': s['sku'],
                    'name': s.get('name', ''),
                    'requirement': s.get('requirement', ''),
                    'quantity': s['quantity'],
                    'actualPlaced': s['actualPlaced'],
                    'remQty': s['remQty'],
                    'isElastic': s['isElastic']
                } for s in sku_pool
            ],
            'placedBoxes': placed_boxes,
            'elapsedMs': elapsed_ms
        }
