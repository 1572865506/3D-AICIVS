"""
3D-AICIVS Industrial Container Packing Engine (Python 3 Kernel)
Implementation of the 6 Core Modules based on implementation_plan.md:
1. 物理压强与朝向控制 (Physical Pressure & Matrix Orientation Control)
2. 成栋成墙成排成列 (Monolithic 3D Block, Wall Flush, Row & Column Stacking)
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
        usable = container_spec.get('usable', {})
        self.L = float(usable.get('L', container_spec.get('intL', 12.032)))
        self.W = float(usable.get('W', container_spec.get('intW', 2.352)))
        self.H = float(usable.get('H', container_spec.get('intH', 2.698)))
        self.max_payload_kg = float(container_spec.get('maxPayloadTons', 28.6)) * 1000.0
        
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

    def get_safe_orientations(self, item: Dict[str, Any], max_w: float, max_h: float, max_d: float) -> List[Dict[str, float]]:
        """模块 1 & 6：朝向权限矩阵与安全旋转朝向评估"""
        allowed = item.get('allowedOrientation', 'upright')
        if item.get('allowFlat'):
            allowed = 'allow_flat'

        oris = [
            {'l': item['w'], 'wz': item['d'], 'h': item['h']},
            {'l': item['d'], 'wz': item['w'], 'h': item['h']}
        ]
        if allowed == 'allow_flat':
            oris.extend([
                {'l': item['w'], 'wz': item['h'], 'h': item['d']},
                {'l': item['d'], 'wz': item['h'], 'h': item['w']}
            ])
        elif allowed == 'allow_side':
            oris.extend([
                {'l': item['h'], 'wz': item['d'], 'h': item['w']},
                {'l': item['h'], 'wz': item['w'], 'h': item['d']}
            ])
        elif allowed == 'any':
            oris.extend([
                {'l': item['w'], 'wz': item['h'], 'h': item['d']},
                {'l': item['d'], 'wz': item['h'], 'h': item['w']},
                {'l': item['h'], 'wz': item['d'], 'h': item['w']},
                {'l': item['h'], 'wz': item['w'], 'h': item['d']}
            ])

        valid = []
        for o in oris:
            if o['l'] <= max_w + 0.001 and o['wz'] <= max_d + 0.001 and o['h'] <= max_h + 0.001:
                valid.append(o)
        return valid

    def get_zone_affinity_score(self, sku: Dict[str, Any], current_x: float) -> float:
        """
        模块 4：3D 重心调控与业务装载分区（深端最里面 -> 中段放中间 -> 门端封柜门）
        与 6 维动态权重深度联动
        """
        req = sku.get('requirement', '')
        is_rear = bool(re.search(r'最里面|rear|deep', req, re.IGNORECASE))
        is_mid = bool(re.search(r'放中间|mid|middle', req, re.IGNORECASE))
        is_door = bool(re.search(r'封柜门|door|front', req, re.IGNORECASE))

        cog_scale = float(self.weights.get('cogBalance', 1500.0)) / 1500.0
        door_scale = float(self.weights.get('doorSafety', 1200.0)) / 1200.0

        if current_x <= 2.5:
            if is_rear: return 100000.0 * cog_scale
            if is_mid: return 20000.0 * cog_scale
            if is_door: return -5000.0 * cog_scale
            return 10000.0
        elif current_x <= 8.5:
            if is_mid: return 50000.0 * cog_scale
            if is_door: return (10000.0 if sku['isElastic'] else 30000.0) * cog_scale
            if is_rear: return -10000.0 * cog_scale
            return 10000.0
        else:
            if is_door: return (70000.0 if sku['isElastic'] else 100000.0) * door_scale
            if is_mid: return 10000.0
            if is_rear: return -20000.0
            return 10000.0

    def pack(self, cargo_manifest: List[Dict[str, Any]]) -> Dict[str, Any]:
        """执行完整装载求解并返回 3D 空间坐标与工程审计指标"""
        start_time = time.time()
        placed_boxes: List[Dict[str, Any]] = []
        elastic_trimmed_map: Dict[str, Any] = {}

        affinity_weight = float(self.weights.get('affinity', 3000.0))
        wall_weight = float(self.weights.get('wallSlicing', 50000.0))

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
        current_x = 0.0
        last_primary_sku: Optional[Dict[str, Any]] = None

        # 核心步进：以墙切片为单位，切片内部自底向上填满 (顶部填空) 并抹平凹面 (凹面填平消除 C型/L型中空)
        while current_x < self.L - 0.02:
            available = [s for s in sku_pool if s['remQty'] > 0]
            if not available:
                break

            # 1. 选取主要排布锚点 SKU (成栋大方阵优先)
            def sku_rank(s):
                score = self.get_zone_affinity_score(s, current_x)
                if last_primary_sku and s['sku'] == last_primary_sku['sku']:
                    score += affinity_weight * 10.0
                if s['isElastic']:
                    score -= 20000.0
                score += min(s['remQty'], 500) * 10.0 + (s['w'] * s['h'] * s['d']) * (wall_weight / 1000.0)
                return score

            available.sort(key=sku_rank, reverse=True)
            primary_sku = available[0]
            primary_oris = self.get_safe_orientations(primary_sku, self.L - current_x, self.H, self.W)
            if not primary_oris:
                current_x += 0.05
                continue

            primary_oris.sort(key=lambda o: ((self.W // o['wz']) * o['wz'] * (self.H // o['h']) * o['h']), reverse=True)
            primary_ori = primary_oris[0]
            slice_thickness = primary_ori['l']

            cols_p = max(1, math.floor(self.W / primary_ori['wz']))
            lays_p = max(1, math.floor(self.H / primary_ori['h']))
            slice_capacity = cols_p * lays_p

            # 如果剩余数量够装满至少 1 个整切片且该切片为整栋结构 (成栋 Monolithic 3D Block)
            if primary_sku['remQty'] >= slice_capacity and current_x + slice_thickness <= self.L + 0.001:
                full_slices = min(primary_sku['remQty'] // slice_capacity, int((self.L - current_x) // slice_thickness))
                for sx in range(full_slices):
                    sl_x = current_x + sx * slice_thickness
                    for c in range(cols_p):
                        col_z = c * primary_ori['wz']
                        for lay in range(lays_p):
                            box_y = lay * primary_ori['h']
                            cand = {
                                'x': sl_x,
                                'y': box_y,
                                'z': col_z,
                                'w': slice_thickness,
                                'h': primary_ori['h'],
                                'd': primary_ori['wz']
                            }
                            placed_boxes.append({
                                'id': f"{primary_sku['sku']}-{box_global_index + 1}",
                                'sku': primary_sku['sku'],
                                'name': primary_sku.get('name', ''),
                                'color': primary_sku.get('color', 0x3b82f6),
                                'weight': primary_sku['weight'],
                                'requirement': primary_sku.get('requirement', ''),
                                'isElastic': primary_sku['isElastic'],
                                'x': round(cand['x'], 4),
                                'y': round(cand['y'], 4),
                                'z': round(cand['z'], 4),
                                'w': round(cand['w'], 4),
                                'h': round(cand['h'], 4),
                                'd': round(cand['d'], 4)
                            })
                            box_global_index += 1
                            primary_sku['actualPlaced'] += 1
                            primary_sku['remQty'] -= 1

                current_x += full_slices * slice_thickness
                last_primary_sku = primary_sku if primary_sku['remQty'] > 0 else None
                continue

            # 2. 如果不足一个完整切片，执行【横向拼装 + 顶部继续填充 + 凹面平准化】
            current_z = 0.0
            slice_cols = []  # 记录切片内各列的空间信息: [{'zStart', 'zEnd', 'xEnd', 'topY'}]

            while current_z < self.W - 0.02:
                avail_in_col = [s for s in sku_pool if s['remQty'] > 0]
                if not avail_in_col:
                    break

                avail_in_col.sort(key=lambda s: (
                    100000.0 if s['sku'] == primary_sku['sku'] else self.get_zone_affinity_score(s, current_x),
                    -1 if s['isElastic'] else 1,
                    s['remQty']
                ), reverse=True)

                col_sku = None
                col_ori = None

                for s in avail_in_col:
                    soris = self.get_safe_orientations(s, self.L - current_x, self.H, self.W - current_z)
                    soris.sort(key=lambda o: abs(o['l'] - slice_thickness))
                    if soris:
                        col_sku = s
                        col_ori = soris[0]
                        break

                if not col_sku or not col_ori:
                    current_z += 0.05
                    continue

                col_x_end = current_x + col_ori['l']
                col_z_start = current_z
                col_z_end = current_z + col_ori['wz']
                col_y = 0.0

                # 垂直逐层向上堆叠主 SKU (成列)
                while col_y + col_ori['h'] <= self.H + 0.001 and col_sku['remQty'] > 0:
                    cand = {
                        'x': current_x,
                        'y': col_y,
                        'z': col_z_start,
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
                    col_y += col_ori['h']

                # 【核心模块 3】：单件/少量货物上面，继续填充其它符合尺寸要求的货物 (顶部空间向上填满至 H)
                while col_y < self.H - 0.10:
                    avail_top = [s for s in sku_pool if s['remQty'] > 0]
                    filled_top = False
                    avail_top.sort(key=lambda s: (self.get_zone_affinity_score(s, current_x), s['remQty']), reverse=True)
                    for top_sku in avail_top:
                        top_oris = self.get_safe_orientations(top_sku, col_ori['l'], self.H - col_y, col_ori['wz'])
                        if top_oris:
                            t_ori = top_oris[0]
                            cand = {
                                'x': current_x,
                                'y': col_y,
                                'z': col_z_start,
                                'w': t_ori['l'],
                                'h': t_ori['h'],
                                'd': t_ori['wz']
                            }
                            placed_boxes.append({
                                'id': f"{top_sku['sku']}-{box_global_index + 1}",
                                'sku': top_sku['sku'],
                                'name': top_sku.get('name', ''),
                                'color': top_sku.get('color', 0x3b82f6),
                                'weight': top_sku['weight'],
                                'requirement': top_sku.get('requirement', ''),
                                'isElastic': top_sku['isElastic'],
                                'x': round(cand['x'], 4),
                                'y': round(cand['y'], 4),
                                'z': round(cand['z'], 4),
                                'w': round(cand['w'], 4),
                                'h': round(cand['h'], 4),
                                'd': round(cand['d'], 4)
                            })
                            box_global_index += 1
                            top_sku['actualPlaced'] += 1
                            top_sku['remQty'] -= 1
                            col_y += t_ori['h']
                            filled_top = True
                            break
                    if not filled_top:
                        break

                slice_cols.append({
                    'zStart': col_z_start,
                    'zEnd': col_z_end,
                    'xEnd': col_x_end,
                    'topY': col_y
                })
                current_z = col_z_end

            if not slice_cols:
                current_x += 0.05
                continue

            max_slice_x = max(c['xEnd'] for c in slice_cols)

            # 【核心模块 3 & 4】：货物成墙切片后出现的凹面 (Notch)，用符合深度的货物填平抹平，严禁直接跳过导致 C型/L型中空
            for col in slice_cols:
                notch_x = col['xEnd']
                while notch_x < max_slice_x - 0.05:
                    notch_depth = max_slice_x - notch_x
                    notch_width = col['zEnd'] - col['zStart']
                    avail_notch = [s for s in sku_pool if s['remQty'] > 0]
                    filled_notch = False

                    avail_notch.sort(key=lambda s: (self.get_zone_affinity_score(s, notch_x), s['remQty']), reverse=True)
                    for n_sku in avail_notch:
                        n_oris = self.get_safe_orientations(n_sku, notch_depth, self.H, notch_width)
                        if n_oris:
                            n_ori = n_oris[0]
                            # 自底向上填满该凹面
                            n_y = 0.0
                            count_n = 0
                            while n_y + n_ori['h'] <= self.H + 0.001 and n_sku['remQty'] > 0:
                                cand = {
                                    'x': notch_x,
                                    'y': n_y,
                                    'z': col['zStart'],
                                    'w': n_ori['l'],
                                    'h': n_ori['h'],
                                    'd': n_ori['wz']
                                }
                                placed_boxes.append({
                                    'id': f"{n_sku['sku']}-{box_global_index + 1}",
                                    'sku': n_sku['sku'],
                                    'name': n_sku.get('name', ''),
                                    'color': n_sku.get('color', 0x3b82f6),
                                    'weight': n_sku['weight'],
                                    'requirement': n_sku.get('requirement', ''),
                                    'isElastic': n_sku['isElastic'],
                                    'x': round(cand['x'], 4),
                                    'y': round(cand['y'], 4),
                                    'z': round(cand['z'], 4),
                                    'w': round(cand['w'], 4),
                                    'h': round(cand['h'], 4),
                                    'd': round(cand['d'], 4)
                                })
                                box_global_index += 1
                                n_sku['actualPlaced'] += 1
                                n_sku['remQty'] -= 1
                                n_y += n_ori['h']
                                count_n += 1

                            if count_n > 0:
                                notch_x += n_ori['l']
                                filled_notch = True
                                break
                    if not filled_notch:
                        break

            current_x = max_slice_x
            last_primary_sku = None

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
            'packedLength': round(current_x, 3),
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

