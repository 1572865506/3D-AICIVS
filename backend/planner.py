# -*- coding: utf-8 -*-
"""
v1.7.0 全局规划层(Global Plan Layer)

设计定位:在单遍贪心构建之前,先解一个"总账"问题--
  给定柜体三围与清单,每个 SKU 用什么朝向,在哪个分区,占多少纵深,装多少箱,
  才能最大化单位纵深体积装载量(volume per depth, vpd)。

与构建层的关系:规划结果是【强先验】而非硬指令--
  内核在主 SKU 评选时给规划 SKU 加 planBonus,但门禁,孤儿抑制,弹性降权,
  硬约束回退全部照常生效；规划段放不下时顺延链自然接管(graceful degradation)。

规划算法(分区深度预算分配):
  1. 分区:柜头段 [0, rear_boundary] / 中段 / 门段 [door_boundary, L](与内核边界一致)。
  2. 每 SKU 全局朝向:枚举安全朝向,vpd = 单切片容量 × 单箱体积 ÷ (厚度+gap),
     取最大者。这是与构建层的关键差异--构建层按"当前截面覆盖率"局部选朝向,
     规划层按"单位纵深体积"全局选朝向(薄而密的朝向可能覆盖率略低但 vpd 更高)。
  3. 分区预算分配:柜头 → 中段 → 门段依次消耗预算。
     每段候选优先级:本区专属 SKU(vpd 降序)→ 溢出货(柜头: 中段>弹性>门货；
     中段: 中段/弹性 > 柜头溢出 > 门货溢出(对齐门禁"非门货耗尽才放门货"语义)；
     门段: 门货 > 一切剩余)。
  4. 逐 SKU 分配整切片数；预算放不下整片但 >= 厚度时允许 1 个部分切片段。
  5. 任何异常返回 None,内核回退纯贪心(fail-safe)。

输出 segment:{sku, ori, zone, x_start, x_end, boxes, slices, partial}
"""
import math
import re
from typing import Dict, Any, List, Optional


def _pitch_fit(total: float, unit: float, gap: float) -> int:
    """gap 网格下的容纳数(与内核 _pitch_fit 语义一致)"""
    if unit <= 0:
        return 0
    return int(math.floor((total + gap + 1e-9) / (unit + gap)))


def _classify(sku: Dict[str, Any]) -> str:
    """分区归类:rear / middle / door / flex(正则与内核一致)"""
    req = sku.get('requirement', '') or ''
    if re.search(r'最里面|rear|deep', req, re.IGNORECASE):
        return 'rear'
    if re.search(r'放中间|mid|middle', req, re.IGNORECASE):
        return 'middle'
    if re.search(r'封柜门|door|front', req, re.IGNORECASE):
        return 'door'
    return 'flex'


def _all_orientations(item: Dict[str, Any]) -> List[Dict[str, float]]:
    """朝向枚举(与内核 get_safe_orientations 同源,不含尺寸过滤)"""
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
    return oris


def _is_elastic(sku: Dict[str, Any]) -> bool:
    req = sku.get('requirement', '') or ''
    return bool(sku.get('isElastic')) or bool(re.search(r'可以少放|可以减少|可减少|调节|按需', req, re.IGNORECASE))


class GlobalPlanBuilder:
    """清单预分析 → 全局排布序列(分区深度预算 × vpd 朝向选择 × 配额)"""

    def __init__(self, L: float, W: float, H: float, gap: float,
                 rear_boundary: float, door_boundary: float):
        self.L = float(L)
        self.W = float(W)
        self.H = float(H)
        self.gap = max(0.0, float(gap or 0.0))
        # 短柜保护(与内核边界语义对齐):柜头段截断到 L；门段起点夹在 [柜头端, L]
        self.rear_end = min(float(rear_boundary), self.L)
        self.door_start = min(max(float(door_boundary), self.rear_end), self.L)

    def build(self, sku_pool: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
        """产出 segment 序列；输入清单为空或无任何可行朝向时返回空列表"""
        rem = {}
        info: Dict[str, Dict[str, Any]] = {}
        for s in sku_pool:
            qty = int(s.get('quantity', 0) or 0)
            if qty <= 0:
                continue
            best = self._best_orientation(s, qty)
            if best is None:
                continue  # 柜内放不下的 SKU 不进规划(构建层按物理不可容纳处理)
            rem[s['sku']] = qty
            info[s['sku']] = best

        if not info:
            return []

        by_sku = {s['sku']: s for s in sku_pool}
        
        # 严格隔离刚性必装件与弹性可核减件 (Rigid-First Planning)
        zones = {
            'rear': [k for k in info if _classify(by_sku[k]) == 'rear' and not _is_elastic(by_sku[k])],
            'middle': [k for k in info if _classify(by_sku[k]) == 'middle' and not _is_elastic(by_sku[k])],
            'door': [k for k in info if _classify(by_sku[k]) == 'door' and not _is_elastic(by_sku[k])],
            'flex': [k for k in info if _classify(by_sku[k]) == 'flex' and not _is_elastic(by_sku[k])],
            'elastic': [k for k in info if _is_elastic(by_sku[k])],
        }
        for z in zones.values():
            z.sort(key=lambda k: info[k]['vpd'], reverse=True)

        segments: List[Dict[str, Any]] = []
        cursor = 0.0

        # Phase 1: 柜头段 [0, rear_end] 刚性件优先足额分配
        cursor = self._allocate('rear', cursor, self.rear_end,
                                zones['rear'] + zones['middle'] + zones['flex'] + zones['door'],
                                rem, info, by_sku, segments)

        # Phase 2: 中段 [cursor, door_start] 刚性件优先足额分配
        cursor = self._allocate('middle', cursor, self.door_start,
                                zones['middle'] + zones['flex'] + zones['rear'] + zones['door'],
                                rem, info, by_sku, segments)

        # Phase 3: 门段 [cursor, L] 刚性件先行装满
        cursor = self._allocate('door', cursor, self.L,
                                zones['door'] + zones['middle'] + zones['flex'] + zones['rear'],
                                rem, info, by_sku, segments)

        # Phase 4: 弹性缓冲件 (如 SKU-14) 仅在所有刚性件规划完毕后,使用全柜最终剩余纵深充填封门
        if zones['elastic'] and cursor < self.L - 0.02:
            self._allocate('door', cursor, self.L,
                           zones['elastic'],
                           rem, info, by_sku, segments)

        return segments

    def _best_orientation(self, sku: Dict[str, Any], qty: int) -> Optional[Dict[str, Any]]:
        """全局最优朝向:最大化单位纵深体积装载量 vpd。
        vpd 按实际可装量折算:min(qty, cap)/cap × 满载 vpd--残量 SKU(如剩 1 箱)
        的真实密度远低于满切片理论值,按理论值排序会把残箱排进黄金区位
        (实测 v1:单箱 SKU 与 50/70 残量 SKU 占据柜头段,基线回退 75 箱)。"""
        box_vol = sku['w'] * sku['d'] * sku['h']
        best = None
        for o in _all_orientations(sku):
            if o['l'] > self.L + 0.001 or o['wz'] > self.W + 0.001 or o['h'] > self.H + 0.001:
                continue
            cols = _pitch_fit(self.W, o['wz'], self.gap)
            lays = _pitch_fit(self.H, o['h'], self.gap)
            if cols <= 0 or lays <= 0:
                continue
            cap = cols * lays
            fill = min(1.0, qty / cap)
            vpd = (cap * box_vol * fill) / (o['l'] + self.gap)
            if best is None or vpd > best['vpd'] + 1e-12:
                best = {'ori': dict(o), 'cap': cap, 'vpd': vpd}
        return best

    def _allocate(self, zone: str, x_start: float, x_end: float,
                  candidates: List[str], rem: Dict[str, int],
                  info: Dict[str, Dict[str, Any]], by_sku: Dict[str, Dict[str, Any]],
                  segments: List[Dict[str, Any]]) -> float:
        """在 [x_start, x_end] 预算内按候选顺序分配整切片/部分切片段,返回段尾游标"""
        cursor = x_start
        budget = max(0.0, x_end - x_start)
        for sku_id in candidates:
            if budget <= 1e-9:
                break
            qty = rem.get(sku_id, 0)
            if qty <= 0:
                continue
            d = info[sku_id]
            thick, cap = d['ori']['l'], d['cap']
            if budget + 1e-9 < thick:
                continue  # 放不下该朝向整片,尝试下一个(更薄的)SKU
            # 预算内能放的切片数:n*(thick+gap) <= budget+gap
            n_fit = int(math.floor((budget + self.gap + 1e-9) / (thick + self.gap)))
            n_need = -(-qty // cap)  # ceil:装完全部数量所需切片数
            slices = max(1, min(n_need, n_fit))
            boxes = min(qty, slices * cap)
            partial = qty > slices * cap  # 预算截断(区别于数量自然收尾)
            depth = slices * thick + (slices - 1) * self.gap
            segments.append({
                'sku': sku_id,
                'ori': dict(d['ori']),
                'zone': zone,
                'x_start': round(cursor, 6),
                'x_end': round(cursor + depth, 6),
                'boxes': boxes,
                'slices': slices,
                'partial': bool(partial),
            })
            cursor += depth + self.gap
            budget -= depth + self.gap
            rem[sku_id] = qty - boxes
        return cursor
