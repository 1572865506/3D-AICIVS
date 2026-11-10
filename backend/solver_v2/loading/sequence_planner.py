"""
装载顺序求解（Installability & Loading Sequence）。

问题：求解器产出的 placements 只保证几何合规，不保证"存在一个物理可执行的装入顺序"。
此前 API 直接把 placements 的枚举下标当作 step 顺序上报，实测 15-SKU 方案在该顺序下
有 764 箱会被更早装入的箱子挡住通道（视觉正常、现场无法装）。

本模块：以箱体几何构造"必须谁先装"的偏序关系，做拓扑排序得到可执行顺序。

依赖关系定义（从门端沿 -X 推入）：
  若 A 位于 B 的入口侧（A.x >= B.x + B.dx - eps）且 A 与 B 在 (y,z) 截面重叠，
  则 B 必须先装入（否则 A 挡在通道上）。

输出：
  - order: 合法的装载顺序（placement_id 列表）
  - cycles: 残余环（非空表示方案物理不可装，需回退/重解）
  - blocked_before: 旧顺序下的受阻箱数（用于报告改进幅度）

被谁调用：backend/api/service.py（构建 loading plan / sequence）、
tests/test_sequence_installability.py。
"""
from typing import Any, Dict, List, Sequence, Tuple


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return min(a1, b1) - max(a0, b0)


def build_dependency_graph(placements: Sequence[Any]) -> Tuple[List[set], int]:
    """返回 (邻接表, 依赖边数)。边 i->j 表示 i 必须先于 j 装入。"""
    boxes = []
    for p in placements:
        if isinstance(p, dict):
            boxes.append((p["x"], p["y"], p["z"], p["dx"], p["dy"], p["dz"]))
        else:
            boxes.append((p.position.x, p.position.y, p.position.z,
                          p.orientation.dx, p.orientation.dy, p.orientation.dz))
    n = len(boxes)
    adj = [set() for _ in range(n)]
    edge_count = 0
    for i, (bx, by, bz, bdx, bdy, bdz) in enumerate(boxes):
        for j, (ax, ay, az, adx, ady, adz) in enumerate(boxes):
            if i == j:
                continue
            # A 位于 B 的入口侧（完全或部分在前）
            if ax < bx + bdx - 1e-3:
                continue
            if _overlap(by, by + bdy, ay, ay + ady) <= 1e-4:
                continue
            if _overlap(bz, bz + bdz, az, az + adz) <= 1e-4:
                continue
            adj[i].add(j)
            edge_count += 1
    return adj, edge_count


def compute_loading_order(
    placements: Sequence[Any],
    container: Any = None,
) -> Dict[str, Any]:
    """
    计算物理可执行的装载顺序。

    返回 {"order": [placement_id...], "cycles": [placement_id...],
          "edge_count": int, "blocked_in_naive_order": int, "feasible": bool}
    """
    ids = [p.get("placement_id") if isinstance(p, dict) else p.placement_id for p in placements]
    n = len(ids)
    if n == 0:
        return {"order": [], "cycles": [], "edge_count": 0,
                "blocked_in_naive_order": 0, "feasible": True}

    adj, edge_count = build_dependency_graph(placements)

    indeg = [0] * n
    for i in range(n):
        for j in adj[i]:
            indeg[j] += 1

    # 确定性优先队列：越深（x 小）、越低（z 小）、越靠左（y 小）越先装
    def _key(i: int):
        p = placements[i]
        if isinstance(p, dict):
            return (round(p["x"], 3), round(p["z"], 3), round(p["y"], 3), ids[i])
        return (round(p.position.x, 3), round(p.position.z, 3), round(p.position.y, 3), ids[i])

    ready = sorted([i for i in range(n) if indeg[i] == 0], key=_key)
    order: List[int] = []
    while ready:
        u = ready.pop(0)
        order.append(u)
        inserted = False
        for v in sorted(adj[u], key=_key):
            indeg[v] -= 1
            if indeg[v] == 0:
                ready.append(v)
                inserted = True
        if inserted:
            ready.sort(key=_key)

    cycles = [ids[i] for i in range(n) if i not in set(order)]

    # 旧（枚举）顺序下的受阻箱数：某箱的前向邻居（必须先于它装入的更深箱）
    # 反而排在它之后 → 该箱装入后通道被封
    naive_pos = {i: i for i in range(n)}
    blocked = 0
    for i in range(n):
        for j in adj[i]:
            if naive_pos[j] < i:   # 更深箱 j 排在 i 之后
                blocked += 1
                break

    return {
        "order": [ids[i] for i in order],
        "cycles": cycles,
        "edge_count": edge_count,
        "blocked_in_naive_order": blocked,
        "feasible": not cycles,
    }
