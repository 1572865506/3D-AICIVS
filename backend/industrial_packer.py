"""
3D-AICIVS Industrial Container Packing Engine (Python 3 Kernel)
Implementation of the 6 Core Modules based on implementation_plan.md:
1. 物理压强与朝向控制 (Physical Pressure & Matrix Orientation Control)
2. 成栋成墙成排成列 (Monolithic 3D Block, Wall Flush, Row & Column Stacking)
3. 尾数箱双重安全拦截与平整度 (Remainder Security & Flatness Control Δh <= 3mm)
4. 3D 动态重心与业务装载分区 (Dynamic 3D CoG & Zone Requirements)
5. 阶梯防倾与超容弹性智能核减 (Anti-Toppling Step & Overcapacity Elastic Trimming)
6. 箱门 1.2m 警戒区防倾倒锁定 (Door Safety Zone Locking K = Dx/H >= 0.50)

=== 约束补全说明（v1.2）===
本版本将原"名义实现"的模块补齐为硬约束：
- 模块1: 新增承重/压强校验（SKU 可选字段 maxStackWeight / maxPressureKgM2）
- 模块4: 新增增量重心状态 + 双向铺列（重心偏哪侧，列就从对侧铺，拉回中心）
- 模块5: 新增阶梯防倾校验（支撑覆盖率 + 支撑质心偏移，防悬挑倾倒）
- 模块6: 激活 door_zone_x 硬约束（门区仅弹性 / 封柜门 / allowDoorZone SKU 可入）
- 模块3: 顶部填空贴合度排序 + flatness 平整度审计报告
- 死权重 verticalStack / notchLeveling 已接入排序决策
所有新约束均可通过 weights 参数调节，向后兼容（未定义新字段的 SKU 不受限制）。
"""

import math
import re
import time
from typing import List, Dict, Any, Optional, Tuple

class IndustrialSmartContainerPacker:
    def __init__(self, container_spec: Dict[str, Any], weights: Optional[Dict[str, float]] = None,
                 gap: float = 0.0, strategy: str = 'cluster', enableCoGBalance: bool = True,
                 usePlan: bool = True, multiStart: bool = True):
        usable = container_spec.get('usable', {})
        self.L = float(usable.get('L', container_spec.get('intL', 12.032)))
        self.W = float(usable.get('W', container_spec.get('intW', 2.352)))
        self.H = float(usable.get('H', container_spec.get('intH', 2.698)))
        self.max_payload_kg = float(container_spec.get('maxPayloadTons', 28.6)) * 1000.0

        # v1.5.0 前后端全参数贯通：
        # - gap: 货物间距（米）。每箱按 pitch = 尺寸 + gap 网格推进（L/W/H 三轴），
        #   支撑判定按"隔 gap 接触"处理（上层箱视为由下层箱承重），审计联动。
        # - strategy: 'cluster' 同品聚合+重力支撑（默认，原行为）/ 'mec' 紧凑空闲块填充
        #   （每个空闲块优先选填充度最高的 SKU/朝向，不保持同品连续性）。
        # - enableCoGBalance: False 时关闭列级重心硬拦截与 cogBalance 分区加权（纯空间推进）。
        # v1.7.0 全局规划层：
        # - usePlan: True 时构建前先跑 GlobalPlanBuilder 求全局排布序列（分区深度预算 ×
        #   vpd 最优朝向 × 配额），作为主 SKU 评选的强先验（planBonus 加权）；
        #   门禁/孤儿抑制/硬约束回退照常生效，规划失败自动回退纯贪心。
        self.gap = max(0.0, float(gap or 0.0))
        self.strategy = strategy if strategy in ('cluster', 'mec') else 'cluster'
        self.enable_cog = bool(enableCoGBalance)
        self.use_plan = bool(usePlan)
        # 多起点择优外壳：pack() 内跑 plan/greedy 两个变体，按综合分
        # （placed×box_w + util×util_w − flatness×flat_w）取最优。
        self.multi_start = bool(multiStart)

        # 模块 6：箱门 1.2m 警戒区边界
        self.door_zone_x = max(0.0, self.L - 1.20)
        # v1.6.0 分区边界动态化（对齐前端 JS 内核语义）：
        # 柜头段 3.2m（最里面）/ 门段起点 L-4.2m（封柜门）/ 中段为两者之间。
        # 短柜保护：门段起点不早于柜头段边界 + 0.1。
        self.rear_boundary = 3.2
        self.door_boundary = max(self.rear_boundary + 0.1, self.L - 4.2)

        default_weights = {
            'affinity': 3000.0,
            'verticalStack': 3500.0,
            'wallSlicing': 50000.0,
            'notchLeveling': 2500.0,
            'cogBalance': 1500.0,
            'doorSafety': 1200.0,
            # 新增约束参数（可调）
            'latLimit': 5.0,            # 横向偏载审计阈值（%）
            'cogHardLimit': 10.0,       # 横向偏载硬拦截阈值（%）：超过才跳过列，默认取 latLimit*2
            'minSupportRatio': 0.70,    # 最小支撑覆盖率（阶梯防倾）v1.6.0 对齐前端三轴评估器 70%
            'maxShiftRatio': 0.35,      # 支撑质心最大偏移比例
            'cogWarnRatio': 0.6,        # 重心预警线 = latLimit * 该比例
            'cogEngageRatio': 0.5,      # 重心硬门控启用线：已装质量 >= 预期总质量 * 该比例才启用列级硬拦截
            'minColHeightRatio': 0.50,  # v1.6.1 孤儿列抑制：尾数段列 SKU 可达列高 < 柜高*该比例时重降权（残箱改走顶部填空/凹面填平）
            'planBonus': 120000.0       # v1.7.0 规划先验权重：规划 SKU 主评选加分（< 孤儿惩罚 200000，孤儿抑制优先于规划）
        }
        self.weights = {**default_weights, **(weights or {})}
        self.lat_limit = float(self.weights.get('latLimit', 5.0))
        self.cog_hard_limit = float(self.weights.get('cogHardLimit', self.lat_limit * 2.0))
        self.min_support_ratio = float(self.weights.get('minSupportRatio', 0.70))
        self.max_shift_ratio = float(self.weights.get('maxShiftRatio', 0.35))
        self.cog_warn_ratio = float(self.weights.get('cogWarnRatio', 0.6))
        self.cog_engage_ratio = float(self.weights.get('cogEngageRatio', 0.5))
        self.min_col_height_ratio = float(self.weights.get('minColHeightRatio', 0.50))
        self.plan_bonus = float(self.weights.get('planBonus', 120000.0))
        # v1.7.0 全局规划：segment 序列 + SKU 池索引（pack() 内填充）
        self._plan_segments: List[Dict[str, Any]] = []
        self._plan_pool: Dict[str, Dict[str, Any]] = {}

        # 增量重心状态（模块4 闭环）
        self._cog_mass = 0.0
        self._cog_mx = 0.0
        self._cog_my = 0.0
        self._cog_mz = 0.0
        # 预期总质量（由 pack() 从清单汇总），用于重心硬门控的启用线判定
        self._cog_expected_mass = 0.0
        self._box_index = 0
        # 约束审计统计
        self.stats = {
            'doorZoneLocked': 0,
            'pressureBlocked': 0,
            'supportBlocked': 0,
            'cogSkippedCols': 0
        }
        # 按 SKU 的拦截明细（用于审计与调试）
        self.blocked_detail: Dict[str, Dict[str, int]] = {}
        self._col_tops: List[float] = []

    def _bump(self, sku: str, reason: str) -> None:
        """记录某 SKU 在某约束下被拦截的次数"""
        d = self.blocked_detail.setdefault(sku, {'doorZone': 0, 'pressure': 0, 'support': 0, 'cogSkip': 0})
        d[reason] = d.get(reason, 0) + 1

    def _pitch_fit(self, total: float, unit: float) -> int:
        """
        gap 网格容纳数：沿某轴按 pitch = unit + gap 推进时，total 内能放几个 unit。
        (n-1)*(unit+gap) + unit <= total  =>  n = floor((total + gap) / (unit + gap))。
        gap=0 时退化为 floor(total / unit)，与旧版行为完全一致。
        """
        if unit <= 0:
            return 0
        pitch = unit + self.gap
        return max(0, int((total + self.gap + 1e-9) // pitch))

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

    @staticmethod
    def _is_door_req(sku: Dict[str, Any]) -> bool:
        """需求声明为封柜门货"""
        return bool(re.search(r'封柜门|door|front', sku.get('requirement', ''), re.IGNORECASE))

    def _gate_candidate_pool(self, available: List[Dict[str, Any]], current_x: float) -> List[Dict[str, Any]]:
        """
        v1.6.0 核心作业区门禁（对齐前端硬过滤语义）：
        未推进到门段（current_x < door_boundary）且尚有非门货时，
        封柜门货不进候选池（既不参与主 SKU 评选，也不参与尾数拼装列填充）。
        非门货耗尽后门禁解除，门货可在剩余空间任意放置。

        v1.6.1 残箱尾段提前解锁：剩余非门货全部为残量不足起整列的残箱时，
        若继续锁门，这批残箱会被迫自起地面列——其足迹上方大足迹 SKU 补不进，
        形成低位孤儿列直接推高 flatness 台阶。此退化尾段视同非门货耗尽，
        门货提前进场接管截面（此时该切片本就处于非门货耗尽临界点）。
        """
        rigid = [s for s in available if not s.get('isElastic')]
        if current_x >= self.door_boundary - 1e-9:
            if rigid:
                return rigid
            return available
        
        rigid_non_door = [s for s in rigid if not self._is_door_req(s)]
        if rigid_non_door:
            return rigid_non_door
        if rigid:
            return rigid
        non_door = [s for s in available if not self._is_door_req(s)]
        if non_door:
            return non_door
        return available

    def _achievable_col_height(self, s: Dict[str, Any], current_x: float, rem_width: float) -> float:
        """SKU 在 (纵深余量, 剩余宽度) 约束下，按当前剩余量可堆出的最高列高"""
        best = 0.0
        for o in self.get_safe_orientations(s, self.L - current_x, self.H, rem_width):
            layers = max(1, self._pitch_fit(self.H, o['h']))
            n = min(s['remQty'], layers)
            h = n * o['h'] + max(0, n - 1) * self.gap
            if h > best:
                best = h
        return best

    def _orphan_penalty(self, s: Dict[str, Any], current_x: float, rem_width: float) -> int:
        """
        v1.6.1 孤儿列抑制：残量过小的 SKU（全部堆叠也达不到柜高 minColHeightRatio）
        自起地面列会形成低位孤儿列——顶面收缩机制下大足迹 SKU 无法补高，
        直接推高 flatness 台阶。此类 SKU 重降权，残箱改由顶部填空/凹面填平消耗。
        全部候选均为残箱时（尾段常态）排序仍生效，不阻断放置。
        """
        # 柜头深处的放最里面货物 (如 SKU-01) 必须允许在 X < 1.0m 落地起排，不受孤儿惩罚
        if current_x < 1.0 and re.search(r'最里面|rear|deep', s.get('requirement', '') or '', re.IGNORECASE):
            return 0
        # 刚性件在门区余货段不受孤儿惩罚，允许混合成排以 100% 装满
        if not s.get('isElastic') and current_x >= self.door_boundary - 0.5:
            return 0
        h = self._achievable_col_height(s, current_x, rem_width)
        return 0 if h >= self.min_col_height_ratio * self.H else 1

    def _plan_sku_at(self, current_x: float) -> Optional[Dict[str, Any]]:
        """
        v1.7.0 规划先验：返回 current_x 所在（或最近未完成）的规划段。
        - 段已越过的 SKU 若仍有剩量（规划滞后），不再回追——贪心按亲和度自行处理，
          避免规划强迫滞留货反复低密度刷进度（#18 实验教训）。
        - 当前段 SKU 已装完（remQty=0）则顺延到下一段，规划提前接班。
        - 规划耗尽返回 None，主评选回落纯贪心。
        """
        if not self._plan_segments:
            return None
        for seg in self._plan_segments:
            if current_x < seg['x_end'] - 1e-9:
                entry = self._plan_pool.get(seg['sku'])
                if entry and entry['remQty'] > 0:
                    return seg
                continue  # 该段 SKU 已装完，看下一段
        return None


    def get_zone_affinity_score(self, sku: Dict[str, Any], current_x: float) -> float:
        """
        模块 4：3D 重心调控与业务装载分区（深端最里面 -> 中段放中间 -> 门端封柜门）
        与 6 维动态权重深度联动
        """
        req = sku.get('requirement', '')
        is_rear = bool(re.search(r'最里面|rear|deep', req, re.IGNORECASE))
        is_mid = bool(re.search(r'放中间|mid|middle', req, re.IGNORECASE))
        is_door = bool(re.search(r'封柜门|door|front', req, re.IGNORECASE))
        is_elastic = sku.get('isElastic', False)

        # 配平关闭：分区只按业务需求评分，不做重心加权（纯空间推进）
        cog_scale = (float(self.weights.get('cogBalance', 1500.0)) / 1500.0) if self.enable_cog else 1.0
        door_scale = float(self.weights.get('doorSafety', 1200.0)) / 1200.0

        # v1.6.0 动态分区边界（对齐前端）：柜头 3.2m / 门段 L-4.2m 起
        if current_x <= self.rear_boundary:
            if is_rear: return 100000.0 * cog_scale
            if is_mid: return 20000.0 * cog_scale
            if is_door: return -5000.0 * cog_scale
            return 10000.0
        elif current_x <= self.door_boundary:
            if is_mid: return 50000.0 * cog_scale
            if is_door: return (10000.0 if sku['isElastic'] else 30000.0) * cog_scale
            if is_rear: return -10000.0 * cog_scale
            return 10000.0
        else:
            if not is_elastic:
                if is_door: return 100000.0 * door_scale
                return 80000.0  # 未装完的刚性货（中段/柜头溢流件）在门区拥有极高优先级，排在弹性门货前
            if is_door: return 10000.0 * door_scale
            if is_rear: return -20000.0
            return 10000.0

    # ------------------------------------------------------------------
    # 约束系统（v1.2 新增）：模块1 承重 / 模块5 防倾 / 模块6 门区 / 模块4 重心
    # ------------------------------------------------------------------

    def _direct_supports(self, cand: Dict[str, float], placed_boxes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """找出直接支撑候选箱的已放置箱子（底面接触[含 gap 容忍] + 投影重叠）"""
        supports = []
        for b in placed_boxes:
            # gap 模式：上层箱 y = 下层箱顶面 + gap，视为由下层箱承重
            if abs(b['y'] + b['h'] + self.gap - cand['y']) > 0.0015:
                continue
            if (b['x'] + b['w'] > cand['x'] + 0.0005 and cand['x'] + cand['w'] > b['x'] + 0.0005 and
                    b['z'] + b['d'] > cand['z'] + 0.0005 and cand['z'] + cand['d'] > b['z'] + 0.0005):
                supports.append(b)
        return supports

    def _check_pressure(self, sku: Dict[str, Any], supports: List[Dict[str, Any]], cand: Dict[str, float]) -> bool:
        """
        模块 1：承重压强校验。
        - maxStackWeight（kg）: 支撑箱允许上方堆叠的总重上限
        - maxPressureKgM2（kg/m²）: 支撑箱允许的压强上限
        未定义任一字段的支撑箱不限制（向后兼容）。
        """
        for b in supports:
            ms = float(b.get('maxStackWeight', 0) or 0)
            if ms > 0 and (b.get('bearing', 0.0) + sku['weight']) > ms + 1e-9:
                return False
            mp = float(b.get('maxPressureKgM2', 0) or 0)
            if mp > 0:
                ox = min(cand['x'] + cand['w'], b['x'] + b['w']) - max(cand['x'], b['x'])
                oz = min(cand['z'] + cand['d'], b['z'] + b['d']) - max(cand['z'], b['z'])
                area = ox * oz
                if area > 1e-6 and (b.get('bearing', 0.0) + sku['weight']) / area > mp + 1e-9:
                    return False
        return True

    def _check_support(self, cand: Dict[str, float], supports: List[Dict[str, Any]]) -> bool:
        """
        模块 5：阶梯防倾校验。
        - 支撑覆盖率：直接支撑接触面积 / 箱底面积 >= minSupportRatio
        - 支撑质心偏移：支撑面积质心与箱体重心（X-Z 投影）偏移 <= maxShiftRatio * min(w,d)
        地面放置（y≈0）直接通过。
        """
        if cand['y'] < 0.001:
            return True
        if not supports:
            return False  # 悬空
        base_area = cand['w'] * cand['d']
        contact = 0.0
        sx_sum = 0.0
        sz_sum = 0.0
        for b in supports:
            ox = min(cand['x'] + cand['w'], b['x'] + b['w']) - max(cand['x'], b['x'])
            oz = min(cand['z'] + cand['d'], b['z'] + b['d']) - max(cand['z'], b['z'])
            if ox > 1e-6 and oz > 1e-6:
                a = ox * oz
                contact += a
                sx_sum += a * (max(cand['x'], b['x']) + ox / 2.0)
                sz_sum += a * (max(cand['z'], b['z']) + oz / 2.0)
        ratio = contact / base_area if base_area > 1e-9 else 0.0
        if ratio < self.min_support_ratio - 1e-9:
            return False
        if contact > 1e-9:
            scx = sx_sum / contact
            scz = sz_sum / contact
            bcx = cand['x'] + cand['w'] / 2.0
            bcz = cand['z'] + cand['d'] / 2.0
            max_shift = self.max_shift_ratio * min(cand['w'], cand['d'])
            if abs(scx - bcx) > max_shift or abs(scz - bcz) > max_shift:
                return False
        return True

    def _door_zone_allowed(self, sku: Dict[str, Any], cand: Dict[str, float]) -> bool:
        """
        模块 6：箱门 1.2m 警戒区硬约束。
        侵入门区（x + w > L - 1.2）的箱子必须是：
        - 弹性 SKU（可以少放），或
        - 需求含"封柜门/door/front"，或
        - 显式声明 allowDoorZone=True
        """
        if cand['x'] + cand['w'] <= self.door_zone_x + 0.0015:
            return True
        if sku.get('isElastic') or sku.get('allowDoorZone'):
            return True
        req = sku.get('requirement', '')
        if re.search(r'封柜门|door|front', req, re.IGNORECASE):
            return True
        return False

    def _cog_add(self, box: Dict[str, Any]) -> None:
        """增量更新重心状态（模块4 闭环）"""
        self._cog_mass += box['weight']
        self._cog_mx += box['weight'] * (box['x'] + box['w'] / 2.0)
        self._cog_my += box['weight'] * (box['y'] + box['h'] / 2.0)
        self._cog_mz += box['weight'] * (box['z'] + box['d'] / 2.0)

    def _cog_lat_pct(self) -> float:
        """当前横向（Z 向）偏载百分比"""
        if self._cog_mass <= 0:
            return 0.0
        cog_z = self._cog_mz / self._cog_mass
        return abs(cog_z - self.W / 2.0) / (self.W / 2.0) * 100.0

    def _col_cog_pass(self, col_cands: List[Dict[str, float]]) -> Tuple[bool, float]:
        """
        模块 4：列级重心预检（不真实放置）。
        预计算"本列主堆叠段"放置后的横向偏载。
        - 装载早期（已装质量 < cogEngageRatio × 预期总质量）：不硬拦截。
          墙切片按 z 从左到右对称铺列，后续列会把重心自然拉回中心；
          早期单列相对总质量占比过大、偏载率虚高（如 46%），逐列硬拦截会饿死装载。
        - 装载后期：仅当新列使偏载"远离中心"（加剧失衡）且超过 cogHardLimit 才拦截。
        返回 (是否通过, 放置后偏载%)。
        """
        if self._cog_mass <= 0:
            return True, 0.0
        # enableCoGBalance=False：关闭列级重心硬拦截（纯空间推进）
        if not self.enable_cog:
            return True, self._cog_lat_pct()
        # 早期放行：已装质量不足预期总质量一定比例时不做硬拦截
        expected = self._cog_expected_mass
        if expected > 0 and self._cog_mass < expected * self.cog_engage_ratio:
            return True, self._cog_lat_pct()
        mass = self._cog_mass
        mz = self._cog_mz
        for c in col_cands:
            mass += c['weight']
            mz += c['weight'] * (c['z'] + c['d'] / 2.0)
        if mass <= 0:
            return True, 0.0
        cog_z = mz / mass
        lat = abs(cog_z - self.W / 2.0) / (self.W / 2.0) * 100.0
        # 只拦截"加剧失衡"的列：新偏载方向不变且幅度更大（拉回中心的列一律放行）
        off_now = self._cog_mz / self._cog_mass - self.W / 2.0
        off_after = cog_z - self.W / 2.0
        if lat > self.cog_hard_limit and abs(off_after) > abs(off_now) + 1e-9:
            return False, lat
        return True, lat

    def _col_main_cands(self, sku: Dict[str, Any], ori: Dict[str, float], x: float, z_start: float) -> List[Dict[str, float]]:
        """预构造列的主堆叠段候选（用于重心预检）"""
        cands = []
        y = 0.0
        while y + ori['h'] <= self.H + 0.001:
            cands.append({
                'x': x, 'y': y, 'z': z_start,
                'w': ori['l'], 'h': ori['h'], 'd': ori['wz'],
                'weight': sku['weight']
            })
            y += ori['h'] + self.gap
        return cands

    def _try_place(self, cand: Dict[str, float], sku: Dict[str, Any], placed_boxes: List[Dict[str, Any]]) -> bool:
        """
        统一放置入口：门区 → 碰撞 → 承重 → 防倾 全约束校验通过后提交。
        提交时同步更新：支撑箱 bearing、全局箱索引、增量重心。
        v1.7.0 硬碰撞守卫：此前内核不重叠完全依赖 x/z/y 网格推进纪律（隐式不变量），
        任何路径打破它（朝向过滤的 1mm 容差、规划朝向切换、cog 跳列推进）都会
        产生物理重叠——实测凹面填平 1mm 侵入相邻列 18 对碰撞。碰撞检查改为
        统一入口的显式硬约束，x 向快速预筛控制开销。
        """
        if not self._door_zone_allowed(sku, cand):
            self.stats['doorZoneLocked'] += 1
            self._bump(sku['sku'], 'doorZone')
            return False
        # v1.7.0 AABB 硬碰撞守卫（x 向预筛 + 精确判定）
        cx0, cx1 = cand['x'], cand['x'] + cand['w']
        for b in placed_boxes:
            if b['x'] >= cx1 + 0.0005 or b['x'] + b['w'] <= cx0 - 0.0005:
                continue
            if self.is_aabb_overlap(cand, b):
                self.stats['collisionBlocked'] = self.stats.get('collisionBlocked', 0) + 1
                self._bump(sku['sku'], 'collision')
                return False
        supports = self._direct_supports(cand, placed_boxes)
        if not self._check_pressure(sku, supports, cand):
            self.stats['pressureBlocked'] += 1
            self._bump(sku['sku'], 'pressure')
            return False
        if not self._check_support(cand, supports):
            self.stats['supportBlocked'] += 1
            self._bump(sku['sku'], 'support')
            return False

        # 模块 1b：最大堆叠层数（同 SKU 投影列内限层，前端 maxStackLayers 字段）
        max_layers = int(sku.get('maxStackLayers', 0) or 0)
        if max_layers > 0 and cand['y'] > 0.001:
            below = 0
            for b in placed_boxes:
                if b['sku'] != sku['sku']:
                    continue
                if b['y'] + b['h'] > cand['y'] + 1e-6:
                    continue
                ox = min(cand['x'] + cand['w'], b['x'] + b['w']) - max(cand['x'], b['x'])
                oz = min(cand['z'] + cand['d'], b['z'] + b['d']) - max(cand['z'], b['z'])
                if ox > 1e-6 and oz > 1e-6:
                    below += 1
            if below + 1 > max_layers:
                self.stats['layerBlocked'] = self.stats.get('layerBlocked', 0) + 1
                self._bump(sku['sku'], 'layer')
                return False

        # commit
        for sup in supports:
            sup['bearing'] = round(sup.get('bearing', 0.0) + sku['weight'], 4)
        self._box_index += 1
        box = {
            'id': f"{sku['sku']}-{self._box_index}",
            'sku': sku['sku'],
            'name': sku.get('name', ''),
            'color': sku.get('color', 0x3b82f6),
            'weight': sku['weight'],
            'requirement': sku.get('requirement', ''),
            'isElastic': sku['isElastic'],
            'maxStackWeight': float(sku.get('maxStackWeight', sku.get('maxBearingKg', 0)) or 0),
            'maxPressureKgM2': float(sku.get('maxPressureKgM2', 0) or 0),
            'bearing': 0.0,
            'x': round(cand['x'], 4),
            'y': round(cand['y'], 4),
            'z': round(cand['z'], 4),
            'w': round(cand['w'], 4),
            'h': round(cand['h'], 4),
            'd': round(cand['d'], 4)
        }
        placed_boxes.append(box)
        sku['actualPlaced'] += 1
        sku['remQty'] -= 1
        self._cog_add(box)
        return True

    # ------------------------------------------------------------------
    # 主求解
    # ------------------------------------------------------------------

    def pack(self, cargo_manifest: List[Dict[str, Any]], debug: bool = False) -> Dict[str, Any]:
        """执行完整装载求解并返回 3D 空间坐标与工程审计指标。

        v1.7.0 多起点择优（外层）：同一清单并行求解「规划先验」与「纯贪心」两个变体，
        按综合分（箱数×box_w + 利用率×util_w − 平整度台阶×flat_w）取最优。
        设计动机：规划层在 gap/混合尺寸清单上大幅增益（+137/+621 箱），但在局部
        排序已近优的清单上（如生产清单 MEC）会干扰截面覆盖（−70/−283 箱）——
        单一求解路径无法同时占优是架构特性，由外层择优兜底而非继续调权重。"""
        if not self.multi_start:
            return self._pack_once(cargo_manifest, debug)

        import copy as _copy
        ms_w = self.weights.get('multiStartWeights', {}) or {}
        box_w = float(ms_w.get('box', 10.0))
        util_w = float(ms_w.get('util', 1000.0))
        flat_w = float(ms_w.get('flatness', 0.1))

        variants = [('plan', True), ('greedy', False)] if self.use_plan else [('single', False)]
        scored = []
        orig_use_plan = self.use_plan
        for label, use_plan in variants:
            self.use_plan = use_plan
            r = self._pack_once(_copy.deepcopy(cargo_manifest), debug)
            flat = r['flatness']['maxStepMm'] if isinstance(r['flatness'], dict) else 0.0
            score = r['totalCount'] * box_w + r['utilization'] * util_w - flat * flat_w
            scored.append((score, label, r))
        self.use_plan = orig_use_plan

        scored.sort(key=lambda t: t[0], reverse=True)
        best = scored[0][2]
        best['multiStart'] = {
            'enabled': True,
            'winner': scored[0][1],
            'variants': [
                {
                    'variant': label,
                    'score': round(score, 1),
                    'placed': r['totalCount'],
                    'util': r['utilization'],
                    'flatnessMm': (r['flatness']['maxStepMm']
                                   if isinstance(r['flatness'], dict) else 0.0)
                } for score, label, r in scored
            ]
        }
        return best

    def _pack_once(self, cargo_manifest: List[Dict[str, Any]], debug: bool = False) -> Dict[str, Any]:
        """单次求解（多起点的一个变体）。可重入：每轮重置全部增量状态。"""
        start_time = time.time()
        placed_boxes: List[Dict[str, Any]] = []
        elastic_trimmed_map: Dict[str, Any] = {}

        # v1.7.0 可重入重置（多起点外壳会连续调用本方法）
        self._cog_mass = 0.0
        self._cog_mx = 0.0
        self._cog_my = 0.0
        self._cog_mz = 0.0
        self._box_index = 0
        self.stats = {'doorZoneLocked': 0, 'pressureBlocked': 0,
                      'supportBlocked': 0, 'cogSkippedCols': 0}
        self.blocked_detail = {}
        self._col_tops = []

        # v1.3 XYZ 多轴保底评估器（软审计）：每墙切片后评估最近切片，终检全量
        from evaluator import XYZFallbackEvaluator
        evaluator = XYZFallbackEvaluator(self.L, self.W, self.H, gap=self.gap)
        last_eval_x = 0.0

        affinity_weight = float(self.weights.get('affinity', 3000.0))
        wall_weight = float(self.weights.get('wallSlicing', 50000.0))
        vs_scale = float(self.weights.get('verticalStack', 3500.0)) / 3500.0
        nl_scale = float(self.weights.get('notchLeveling', 2500.0)) / 2500.0

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

        # 预期总质量：重心硬门控启用线判定基准
        self._cog_expected_mass = sum(s['weight'] * s['quantity'] for s in sku_pool)

        # v1.7.0 全局规划层：构建前求解排布序列（分区深度预算 × vpd 最优朝向 × 配额），
        # 作为主 SKU 评选强先验。规划失败/空清单 → 空规划，回退纯贪心（fail-safe）。
        self._plan_segments = []
        self._plan_pool = {s['sku']: s for s in sku_pool}
        if self.use_plan:
            try:
                from planner import GlobalPlanBuilder
                builder = GlobalPlanBuilder(self.L, self.W, self.H, self.gap,
                                            self.rear_boundary, self.door_boundary)
                self._plan_segments = builder.build(sku_pool) or []
            except Exception:
                self._plan_segments = []

        current_x = 0.0
        last_primary_sku: Optional[Dict[str, Any]] = None

        # 核心步进：以墙切片为单位，切片内部自底向上填满 (顶部填空) 并抹平凹面 (凹面填平消除 C型/L型中空)
        # v1.4.1 防卡死兜底：浮点累加可能让 current_x 停在边界 (如 11.40) 而 full_slices 算成 0，
        # 导致"放置成功但 x 不推进"的无限循环。stall_guard 强制保证 x 单调推进。
        stall_count = 0
        stall_prev_x = -1.0
        while current_x < self.L - 0.02:
            if current_x - stall_prev_x < 1e-9:
                stall_count += 1
                if stall_count > 3:
                    current_x += 0.05
                    stall_count = 0
                    continue
            else:
                stall_count = 0
            stall_prev_x = current_x

            available = [s for s in sku_pool if s['remQty'] > 0]
            if not available:
                break
            # v1.6.0 门禁硬过滤：未到门段时封柜门货不进主 SKU 候选池
            available = self._gate_candidate_pool(available, current_x)
            if not available:
                break

            # v1.7.0 规划先验：当前 x 的规划段 SKU（一次求值，两套排名共用）
            plan_seg = self._plan_sku_at(current_x)
            plan_sku_id = plan_seg['sku'] if plan_seg else None

            # 1. 选取主要排布锚点 SKU (成栋大方阵优先)
            def sku_rank(s):
                score = self.get_zone_affinity_score(s, current_x)
                if last_primary_sku and s['sku'] == last_primary_sku['sku']:
                    score += affinity_weight * 10.0
                if s['isElastic']:
                    score -= 20000.0
                score += min(s['remQty'], 500) * 10.0 + (s['w'] * s['h'] * s['d']) * (wall_weight / 1000.0)
                # v1.6.1 孤儿列抑制：残量不足起整列的 SKU 不担任主 SKU——
                # 否则残箱滞留主评选反复触发低密度尾数拼装（刷 x 进度），
                # 或以其为锚自起孤儿列。残箱由顶部填空/凹面填平消耗。
                if self._orphan_penalty(s, current_x, self.W):
                    score -= 200000.0
                # v1.7.0 规划先验：规划段 SKU 加分（孤儿抑制优先——残箱规划段不强迫任主 SKU，
                # 与 #18 反滞留设计一致：残箱由顶部填空/凹面填平消耗）
                elif plan_sku_id and s['sku'] == plan_sku_id:
                    score += self.plan_bonus
                return score

            def mec_rank(s):
                """MEC 紧凑空闲块填充：优先选能把当前剩余截面填得最满的 SKU/朝向。
                不保持同品连续性（无 affinity 粘滞）、不按体积偏好，只看截面填充度；
                剩余数量不足铺满一个截面时按比例打折，避免选中后立刻转尾数拼装。"""
                rem_x = self.L - current_x
                best = 0.0
                for o in self.get_safe_orientations(s, rem_x, self.H, self.W):
                    cols = self._pitch_fit(self.W, o['wz'])
                    lays = self._pitch_fit(self.H, o['h'])
                    if cols <= 0 or lays <= 0:
                        continue
                    cover = (cols * o['wz'] * lays * o['h']) / (self.W * self.H)
                    cap = cols * lays
                    if s['remQty'] < cap:
                        cover *= s['remQty'] / cap
                    best = max(best, cover)
                score = 1000000.0 * best
                if s['isElastic']:
                    score -= 20000.0
                score += min(s['remQty'], 500) * 10.0
                # v1.6.1 孤儿列抑制（同 cluster sku_rank）
                if self._orphan_penalty(s, current_x, self.W):
                    score -= 200000.0
                # v1.7.0 规划先验（同 cluster：孤儿抑制优先）
                elif plan_sku_id and s['sku'] == plan_sku_id:
                    score += self.plan_bonus
                return score

            available.sort(key=(mec_rank if self.strategy == 'mec' else sku_rank), reverse=True)

            # 主 SKU 顺延链：排名靠前但当前剩余长度放不下的 SKU，顺延给下一个能放的。
            # 否则剩余尾段会被"排不上号"的 SKU 卡死，弹性 SKU 大批滞留 → 利用率暴跌。
            primary_sku = None
            primary_ori = None
            primary_oris = []
            for cand_sku in available:
                cand_oris = self.get_safe_orientations(cand_sku, self.L - current_x, self.H, self.W)
                if not cand_oris:
                    continue
                # 截面覆盖优先（gap 网格下用 pitch 容纳数计算）
                cand_oris.sort(key=lambda o: (self._pitch_fit(self.W, o['wz']) * o['wz'] *
                                              self._pitch_fit(self.H, o['h']) * o['h']), reverse=True)
                primary_sku = cand_sku
                primary_ori = cand_oris[0]
                primary_oris = cand_oris
                break
            if not primary_sku or not primary_ori:
                current_x += 0.05
                continue

            # v1.7.0 规划朝向覆盖：当选主 SKU 即规划段 SKU 时，整片/部分切片改用规划层
            # 全局最优朝向（vpd 最大）——构建层默认按"当前截面覆盖率"局部选朝向，
            # 规划层按"单位纵深体积装载量"全局选朝向，两者可能不同（薄而密朝向 vpd 更高）。
            if plan_seg and primary_sku['sku'] == plan_seg['sku']:
                po = plan_seg['ori']
                for o in primary_oris:
                    if (abs(o['l'] - po['l']) < 1e-6 and abs(o['wz'] - po['wz']) < 1e-6
                            and abs(o['h'] - po['h']) < 1e-6):
                        primary_ori = o
                        break

            slice_thickness = primary_ori['l']

            # gap 网格：列/层的 pitch = 尺寸 + gap（gap=0 时与旧版 floor 一致）
            cols_p = max(1, self._pitch_fit(self.W, primary_ori['wz']))
            lays_p = max(1, self._pitch_fit(self.H, primary_ori['h']))
            slice_capacity = cols_p * lays_p

            if debug:
                print(f"[DBG] x={current_x:.3f} primary={primary_sku['sku']} rem={primary_sku['remQty']} cap={slice_capacity} thick={slice_thickness:.3f} ori=({primary_ori['l']:.3f},{primary_ori['wz']:.3f},{primary_ori['h']:.3f})")

            # 如果剩余数量够装满至少 1 个整切片且该切片为整栋结构 (成栋 Monolithic 3D Block)
            if primary_sku['remQty'] >= slice_capacity and current_x + slice_thickness <= self.L + 0.001:
                # v1.4.1 浮点容差：self.L - current_x 在边界时可能为 0.5999999...，直接 // 得到 0
                # → full_slices=0 → 整片"成功"但 x 不推进 → 死循环。加 1e-6 容差修正。
                # v1.5.0 gap 网格：pitch = thickness + gap（gap=0 时与旧版一致）
                full_slices = min(primary_sku['remQty'] // slice_capacity,
                                  self._pitch_fit(self.L - current_x + 1e-6, slice_thickness))
                if full_slices < 1:
                    # 理论上已被上方条件排除；此处兜底：不足 1 整片时直接走尾数拼装
                    full_slices = 1 if current_x + slice_thickness <= self.L + 0.001 else 0
                # 整片预检：任一箱违反硬约束（门区/承重/防倾）则整片回退，改走尾数拼装
                pre_len = len(placed_boxes)
                pre_idx = self._box_index
                pre_rem = primary_sku['remQty']
                pre_act = primary_sku['actualPlaced']
                pre_mass, pre_mx, pre_my, pre_mz = self._cog_mass, self._cog_mx, self._cog_my, self._cog_mz
                pre_bear = [b.get('bearing', 0.0) for b in placed_boxes]

                blocked = False
                for sx in range(full_slices):
                    sl_x = current_x + sx * (slice_thickness + self.gap)
                    # v1.3 层优先：同层 z 向铺满再升层（顶面齐平，层间支撑天然完整，
                    # 消除栋优先的列高参差 → 栋顶空洞）。约束路径与栋优先等价：
                    # 每层箱子站在同 SKU 下层上，支撑/承重校验结果一致，仅中间状态不同。
                    for lay in range(lays_p):
                        box_y = lay * (primary_ori['h'] + self.gap)
                        for c in range(cols_p):
                            col_z = c * (primary_ori['wz'] + self.gap)
                            cand = {
                                'x': sl_x, 'y': box_y, 'z': col_z,
                                'w': slice_thickness, 'h': primary_ori['h'], 'd': primary_ori['wz']
                            }
                            if not self._try_place(cand, primary_sku, placed_boxes):
                                blocked = True
                                break
                        if blocked:
                            break
                    if blocked:
                        break

                if blocked:
                    # 整片回退，改走尾数拼装（该切片按列逐箱尝试，符合约束的仍可放入）
                    if debug:
                        print(f"[DBG]   full-slice BLOCKED, rollback to tail-pack")
                    del placed_boxes[pre_len:]
                    self._box_index = pre_idx
                    primary_sku['remQty'] = pre_rem
                    primary_sku['actualPlaced'] = pre_act
                    self._cog_mass, self._cog_mx, self._cog_my, self._cog_mz = pre_mass, pre_mx, pre_my, pre_mz
                    # 恢复 bearing：回退段位于 placed_boxes 尾部，已整体删除；若回退段曾压在前段箱上，
                    # 需还原前段 bearing（整片预检时只有 primary 参与，预检失败回退即还原）
                    for i, b in enumerate(placed_boxes[:pre_len]):
                        b['bearing'] = pre_bear[i]
                else:
                    # v1.3 评估最近墙切片（软审计，不阻塞）
                    slice_pitch = slice_thickness + self.gap
                    evaluator.evaluate(placed_boxes, sku_pool, last_eval_x,
                                       current_x + full_slices * slice_pitch,
                                       self.get_safe_orientations)
                    last_eval_x = current_x + full_slices * slice_pitch
                    if full_slices < 1:
                        # v1.4.1 兜底：full_slices=0 时强制前进，杜绝 x 停滞死循环
                        current_x += 0.05
                    else:
                        current_x += full_slices * slice_pitch
                    last_primary_sku = primary_sku if primary_sku['remQty'] > 0 else None
                    continue

            # v1.6.2 部分切片（分级触发）：主 SKU 剩量 ≥50% 整栋容量但不足整栋时，
            # 按层优先铺残量成栋——散列尾数拼装会把这批货拆成稀疏列+顶部填空，末端
            # 密度显著低于同切片成栋结构。触发条件按策略分级：
            # - 终局（剩余纵深 <2 个整切片）：cluster / mec 均触发——此时纵深已无
            #   更优用途，成栋密度必然占优；
            # - 中段：仅 mec 触发——半栋切片留下的顶部/侧面空闲可被 mec 的空闲块
            #   回填补偿；cluster 无回填能力，中段半栋只会低密度消耗纵深、饿死
            #   高密度门货（gap 用例实测回退 110 箱）。
            # 中途遇硬约束即止（已放置箱均通过校验，保留）；首箱即失败则回退尾数拼装。
            is_terminal = (current_x + 2 * (slice_thickness + self.gap)
                           > self.L + 0.001)
            if (primary_sku['remQty'] * 2 >= slice_capacity and
                    current_x + slice_thickness <= self.L + 0.001 and
                    (is_terminal or self.strategy == 'mec')):
                placed_any = False
                aborted = False
                for lay in range(lays_p):
                    if aborted or primary_sku['remQty'] <= 0:
                        break
                    box_y = lay * (primary_ori['h'] + self.gap)
                    for c in range(cols_p):
                        if primary_sku['remQty'] <= 0:
                            break
                        col_z = c * (primary_ori['wz'] + self.gap)
                        cand = {
                            'x': current_x, 'y': box_y, 'z': col_z,
                            'w': slice_thickness, 'h': primary_ori['h'], 'd': primary_ori['wz']
                        }
                        if not self._try_place(cand, primary_sku, placed_boxes):
                            aborted = True
                            break
                        placed_any = True
                if placed_any:
                    if debug:
                        print(f"[DBG] x={current_x:.3f} partial-slice {primary_sku['sku']} "
                              f"rem_after={primary_sku['remQty']}")
                    slice_pitch = slice_thickness + self.gap
                    evaluator.evaluate(placed_boxes, sku_pool, last_eval_x,
                                       current_x + slice_pitch, self.get_safe_orientations)
                    last_eval_x = current_x + slice_pitch
                    current_x += slice_pitch
                    last_primary_sku = primary_sku if primary_sku['remQty'] > 0 else None
                    continue
                # 首箱即被硬约束拦截 → 落入下方尾数拼装

            # 2. 如果不足一个完整切片，执行【横向拼装 + 顶部继续填充 + 凹面平准化】
            #    模块4 重心闭环：保持单向铺列（z 递增），列堆叠前做重心预检，
            #    超限列跳过（避免重箱集中一侧导致横向偏载超标）
            z_low = 0.0
            slice_cols = []  # 记录切片内各列的空间信息: [{'zStart', 'zEnd', 'xEnd', 'topY'}]

            while z_low < self.W - 0.02:
                avail_in_col = [s for s in sku_pool if s['remQty'] > 0]
                if not avail_in_col:
                    break
                # v1.6.0 门禁硬过滤：尾数拼装列同样受核心作业区门禁约束
                avail_in_col = self._gate_candidate_pool(avail_in_col, current_x)
                if not avail_in_col:
                    break

                col_sku = None
                col_ori = None
                rem_width = self.W - z_low

                # v1.6.1 残箱终局退出：柜内已有成列结构且当前候选全部为残箱
                # （残量不足起整列）——继续铺列只会自起孤儿地面列，放不进的
                # 残箱按物理无法容纳处理（宁可少装零星几箱，不造 flatness 台阶）。
                # 纯小批量清单（从未建立成列结构）不受影响，仍正常铺列。
                if self._col_tops and all(
                        self._orphan_penalty(s, current_x, rem_width) > 0 for s in avail_in_col):
                    break

                if self.strategy == 'mec':
                    # MEC 紧凑空闲块填充：按"剩余宽度填充度"选列 SKU（能最紧密铺满 rem_width 的优先）
                    def col_rank_mec(s):
                        fit = 0.0
                        for o in self.get_safe_orientations(s, self.L - current_x, self.H, rem_width):
                            cols = self._pitch_fit(rem_width, o['wz'])
                            if cols > 0:
                                fit = max(fit, (cols * o['wz'] / rem_width) * min(1.0, s['remQty'] / cols))
                        return (-self._orphan_penalty(s, current_x, rem_width),
                                1000000.0 * fit, -1 if s['isElastic'] else 1, s['remQty'])
                    avail_in_col.sort(key=col_rank_mec, reverse=True)
                else:
                    # v1.6.1 孤儿列抑制（首要键，跨分区生效）：
                    # 残量不足起整列的 SKU 一律不自起地面列（列顶收缩后大足迹 SKU
                    # 补不进 → flatness 台阶），残箱改走顶部填空/凹面填平。
                    # 早期版本曾因残箱滞留主 SKU 评选引发低密度尾数拼装刷进度——
                    # 现主评选（sku_rank/mec_rank）已施加同款惩罚，无滞留风险。
                    avail_in_col.sort(key=lambda s: (
                        -self._orphan_penalty(s, current_x, rem_width),
                        100000.0 * vs_scale if s['sku'] == primary_sku['sku'] else self.get_zone_affinity_score(s, current_x),
                        -1 if s['isElastic'] else 1,
                        s['remQty']
                    ), reverse=True)

                for s in avail_in_col:
                    soris = self.get_safe_orientations(s, self.L - current_x, self.H, rem_width)
                    soris.sort(key=lambda o: abs(o['l'] - slice_thickness))
                    if not soris:
                        continue
                    # 约束预检（门区/承重/防倾），仅检查该 SKU 的首箱能否放入
                    probe = {'x': current_x, 'y': 0.0, 'z': z_low, 'w': soris[0]['l'], 'h': soris[0]['h'], 'd': soris[0]['wz']}
                    probe_supports = self._direct_supports(probe, placed_boxes)
                    if (self._door_zone_allowed(s, probe) and
                            self._check_pressure(s, probe_supports, probe) and
                            self._check_support(probe, probe_supports)):
                        col_sku = s
                        col_ori = soris[0]
                        break

                if not col_sku or not col_ori:
                    z_low += 0.05
                    continue

                col_z_start = z_low
                col_z_end = col_z_start + col_ori['wz']
                if col_z_end > self.W + 0.001:
                    z_low += 0.05
                    continue

                # 模块4：列级重心预检（主堆叠段）——超限则跳过本列（避免横向偏载超标）
                fwd_cands = self._col_main_cands(col_sku, col_ori, current_x, col_z_start)
                ok_f, lat_f = self._col_cog_pass(fwd_cands)
                if not ok_f:
                    self.stats['cogSkippedCols'] += 1
                    self._bump(col_sku['sku'], 'cogSkip')
                    z_low += col_ori['wz']
                    continue

                col_x_end = current_x + col_ori['l']
                col_y = 0.0

                # 垂直逐层向上堆叠主 SKU (成列)，约束逐箱校验（gap 网格：层间留 gap）
                while col_y + col_ori['h'] <= self.H + 0.001 and col_sku['remQty'] > 0:
                    cand = {
                        'x': current_x, 'y': col_y, 'z': col_z_start,
                        'w': col_ori['l'], 'h': col_ori['h'], 'd': col_ori['wz']
                    }
                    if not self._try_place(cand, col_sku, placed_boxes):
                        break  # 约束拦截，本列停止向上堆叠
                    col_y += col_ori['h'] + self.gap

                # 【核心模块 3】：单件/少量货物上面，继续填充其它符合尺寸要求的货物 (顶部空间向上填满至 H)
                #    模块 3 加强：贴合度优先——优先选择高度接近剩余缺口的箱子，缩小顶面台阶差
                #    防倾修正：顶部箱逐层收缩——尺寸限制用"当前列顶面实际尺寸"，防止悬挑被防倾拦截
                top_limit_l = col_ori['l']
                top_limit_wz = col_ori['wz']
                while col_y < self.H - 0.10:
                    avail_top = self._gate_candidate_pool(
                        [s for s in sku_pool if s['remQty'] > 0], current_x)
                    if not avail_top:
                        break
                    filled_top = False
                    if self.strategy == 'mec':
                        # MEC：底面积大者优先（更紧凑地填满顶部缺口）
                        avail_top.sort(key=lambda s: (s['w'] * s['d'], s['remQty']), reverse=True)
                    else:
                        avail_top.sort(key=lambda s: (
                            self.get_zone_affinity_score(s, current_x),
                            s['remQty']
                        ), reverse=True)
                    for top_sku in avail_top:
                        # v1.7.0 顶面收缩容差校准：允许侵入量 = min(gap, 1mm)——
                        # gap=0 时严格贴合（1mm 侵入即碰撞，实测 18 对）；gap>0 时侵入吃的是
                        # 列间隙（物理合法，旧版 +0.001 行为保留，gap 用例曾因此多装 105 箱）
                        tol = min(self.gap, 0.001)
                        top_oris = self.get_safe_orientations(top_sku, top_limit_l - 0.001 + tol,
                                                              self.H - col_y, top_limit_wz - 0.001 + tol)
                        if not top_oris:
                            continue
                        # 贴合度：优先选中高度与剩余缺口最接近的朝向（减小顶面台阶）
                        top_oris.sort(key=lambda o: abs(o['h'] - (self.H - col_y)))
                        t_ori = top_oris[0]
                        cand = {
                            'x': current_x, 'y': col_y, 'z': col_z_start,
                            'w': t_ori['l'], 'h': t_ori['h'], 'd': t_ori['wz']
                        }
                        if not self._try_place(cand, top_sku, placed_boxes):
                            continue  # 约束拦截，试下一个 SKU
                        col_y += t_ori['h'] + self.gap
                        # 顶面收缩：下一层只能放在本层顶面上
                        top_limit_l = t_ori['l']
                        top_limit_wz = t_ori['wz']
                        filled_top = True
                        break
                    if not filled_top:
                        break

                self._col_tops.append(col_y)
                slice_cols.append({
                    'zStart': col_z_start,
                    'zEnd': col_z_end,
                    'xEnd': col_x_end,
                    'topY': col_y
                })
                # 单向推进（z 递增铺列，gap 网格：列间留 gap）
                z_low = col_z_end + self.gap

            if not slice_cols:
                if debug:
                    print(f"[DBG]   no columns placed at x={current_x:.3f}, skip +0.05")
                current_x += 0.05
                continue

            max_slice_x = max(c['xEnd'] for c in slice_cols)
            if debug:
                print(f"[DBG]   tail-pack cols={len(slice_cols)} max_slice_x={max_slice_x:.3f}")

            # 【核心模块 3 & 4】：货物成墙切片后出现的凹面 (Notch)，用符合深度的货物填平抹平，严禁直接跳过导致 C型/L型中空
            for col in slice_cols:
                notch_x = col['xEnd']
                while notch_x < max_slice_x - 0.05:
                    notch_depth = max_slice_x - notch_x
                    notch_width = col['zEnd'] - col['zStart']
                    avail_notch = self._gate_candidate_pool(
                        [s for s in sku_pool if s['remQty'] > 0], notch_x)
                    if not avail_notch:
                        break
                    filled_notch = False

                    # 死权重接入：notchLeveling 缩放"深度贴合度"在候选排序中的权重
                    # 贴合度 = 凹面深度与该 SKU 可摆放深度的接近程度（越小越贴合）
                    def notch_fit(s):
                        soris = self.get_safe_orientations(s, notch_depth, self.H, notch_width)
                        if not soris:
                            return float('inf')
                        best_l = min(soris, key=lambda o: abs(o['l'] - notch_depth))['l']
                        return abs(best_l - notch_depth) * nl_scale

                    if self.strategy == 'mec':
                        # MEC：凹面深度贴合度优先（不加业务分区权重）
                        avail_notch.sort(key=lambda s: (-notch_fit(s), -s['remQty']), reverse=True)
                    else:
                        avail_notch.sort(key=lambda s: (self.get_zone_affinity_score(s, notch_x), notch_fit(s), -s['remQty']), reverse=True)
                    for n_sku in avail_notch:
                        # v1.7.0 凹面宽度容差校准：侵入量 = min(gap, 1mm)，同顶面收缩逻辑
                        n_oris = self.get_safe_orientations(n_sku, notch_depth, self.H,
                                                            notch_width - 0.001 + min(self.gap, 0.001))
                        if not n_oris:
                            continue
                        # 深度贴合优先（l 越接近凹面深度越好）
                        n_oris.sort(key=lambda o: abs(o['l'] - notch_depth))
                        n_ori = n_oris[0]
                        # 自底向上填满该凹面（gap 网格：层间留 gap）
                        n_y = 0.0
                        count_n = 0
                        while n_y + n_ori['h'] <= self.H + 0.001 and n_sku['remQty'] > 0:
                            cand = {
                                'x': notch_x, 'y': n_y, 'z': col['zStart'],
                                'w': n_ori['l'], 'h': n_ori['h'], 'd': n_ori['wz']
                            }
                            if not self._try_place(cand, n_sku, placed_boxes):
                                break
                            n_y += n_ori['h'] + self.gap
                            count_n += 1

                        if count_n > 0:
                            notch_x += n_ori['l'] + self.gap
                            filled_notch = True
                            break
                        elif nl_scale != 1.0:
                            # notchLeveling 权重参与候选排序：贴合度更高的 SKU 优先
                            pass
                    if not filled_notch:
                        break

            current_x = max_slice_x
            # v1.3 评估最近墙切片（软审计，不阻塞）
            evaluator.evaluate(placed_boxes, sku_pool, last_eval_x, current_x, self.get_safe_orientations)
            last_eval_x = current_x
            last_primary_sku = None

        # v1.3 终检：全量 XYZ 评估（软审计）
        final_audit = evaluator.evaluate(placed_boxes, sku_pool, 0.0, self.L, self.get_safe_orientations)

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

        # 模块 4：3D 动态重心与轴荷偏载计算器（最终审计，基于最终放置结果）
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

        # 模块 6 最终审计：门区内违规箱计数（应为 0）
        door_zone_violations = 0
        for b in placed_boxes:
            if b['x'] + b['w'] > self.door_zone_x + 0.0015:
                if not (b['isElastic'] or b.get('allowDoorZone') or re.search(r'封柜门|door|front', b.get('requirement', ''), re.IGNORECASE)):
                    door_zone_violations += 1

        # 模块 3 平整度审计：列顶面台阶差（Δh）
        if self._col_tops:
            max_top = max(self._col_tops)
            min_top = min(self._col_tops)
            smooth_cols = sum(1 for t in self._col_tops if abs(t - max_top) <= 0.003)
            flatness = {
                'maxStepMm': round((max_top - min_top) * 1000.0, 1),
                'smoothColRatio': round(smooth_cols / len(self._col_tops) * 100.0, 1),
                'totalCols': len(self._col_tops)
            }
        else:
            flatness = {'maxStepMm': 0.0, 'smoothColRatio': 100.0, 'totalCols': 0}

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
            'params': {
                'gap': self.gap,
                'strategy': self.strategy,
                'enableCoGBalance': self.enable_cog,
                'usePlan': self.use_plan
            },
            'plan': {
                'enabled': bool(self._plan_segments),
                'segments': [
                    {
                        'sku': seg['sku'],
                        'zone': seg['zone'],
                        'boxes': seg['boxes'],
                        'slices': seg['slices'],
                        'partial': seg['partial'],
                        'xStart': seg['x_start'],
                        'xEnd': seg['x_end'],
                        'ori': seg['ori']
                    } for seg in self._plan_segments
                ]
            },
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
            'constraints': {
                'doorZoneLocked': self.stats['doorZoneLocked'],
                'pressureBlocked': self.stats['pressureBlocked'],
                'supportBlocked': self.stats['supportBlocked'],
                'cogSkippedCols': self.stats['cogSkippedCols'],
                'doorZoneViolations': door_zone_violations,
                'blockedDetail': self.blocked_detail
            },
            'flatness': flatness,
            'audit': {
                'floatingCount': final_audit['floatingCount'],
                'hollowVolumeM3': final_audit['hollowVolumeM3'],
                'hollowRatio': final_audit['hollowRatio'],
                'missedVolumeM3': final_audit['missedVolumeM3'],
                'missedRatio': final_audit['missedRatio'],
                'evaluateCount': evaluator.eval_count,
                'floatingBoxes': final_audit['floatingBoxes'],
                'missedRegions': final_audit['missedRegions']
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
