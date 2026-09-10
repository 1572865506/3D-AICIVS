"""固定布局的人工逐箱直线入柜检查；输入最终布局，输出顺序、状态及失败证据。

按支撑和直线插入遮挡建立依赖，每步独立验证暂态布局。预算耗尽保持未验证。
不支持倾斜插入、吊装或临时支架；这些情形不得由本检查宣称可执行。
"""
import heapq
import time
from backend.solver_v2.validation.independent_validator import IndependentGlobalValidator


def check_sequence(container, cargo, placements, budget_sec=2.0):
    deadline = time.monotonic()+budget_sec
    unknown = {'status': 'NOT_EVALUATED', 'order': [], 'reasons': ['SEQUENCE_BUDGET_EXCEEDED']}
    n = len(placements)
    outgoing = [set() for _ in placements]
    indegree = [0]*n

    def add(a,b):
        if b not in outgoing[a]:
            outgoing[a].add(b)
            indegree[b] += 1

    for i,p in enumerate(placements):
        if time.monotonic() >= deadline:
            return unknown
        for j,q in enumerate(placements):
            if i == j:
                continue
            ox = min(p.max_x,q.max_x)-max(p.min_x,q.min_x)
            oy = min(p.max_y,q.max_y)-max(p.min_y,q.min_y)
            oz = min(p.max_z,q.max_z)-max(p.min_z,q.min_z)
            if abs(p.max_z-q.min_z) <= .001 and p.min_z < q.min_z and ox > 1e-4 and oy > 1e-4:
                add(i,j)
            # 柜门在 +X；深处箱子的扫掠路径被外侧箱子占据时，深处必须先装。
            if q.min_x >= p.max_x-1e-4 and oy > 1e-4 and oz > 1e-4:
                add(i,j)
    ready = [(placements[i].min_x, placements[i].min_z, i) for i in range(n) if not indegree[i]]
    heapq.heapify(ready)
    order=[]
    while ready:
        if time.monotonic() >= deadline:
            return unknown
        _,_,i=heapq.heappop(ready)
        order.append(i)
        for j in sorted(outgoing[i]):
            indegree[j]-=1
            if not indegree[j]:
                heapq.heappush(ready,(placements[j].min_x,placements[j].min_z,j))
    if len(order) != n:
        return {'status':'INFEASIBLE','order':[], 'reasons':['DEPENDENCY_CYCLE']}
    prefix=[]
    for i in order:
        if time.monotonic() >= deadline:
            return unknown
        prefix.append(placements[i])
        result=IndependentGlobalValidator.validate(container,prefix,cargo)
        if time.monotonic() >= deadline:
            return unknown
        if not result.is_valid:
            return {'status':'INFEASIBLE','order':[], 'reasons':result.rejection_reasons,
                    'failed_step':len(prefix)}
    return {'status':'FEASIBLE','order':[placements[i] for i in order], 'reasons':[],
            'assumptions':{'mode':'MANUAL_CARTON','insertion_axis':'-X','clearance_m':0.0}}
