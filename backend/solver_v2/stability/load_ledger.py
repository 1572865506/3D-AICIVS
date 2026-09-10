"""求解器增量载荷账本：输入候选几何，输出所有下层载荷增量，预检通过后提交。

采用接触面积归一化分摊（静态均布载荷假设）；守恒传递自重与上层载荷。
独立验证器另行从最终几何复算，不消费此账本。
"""


class LoadLedger:
    def __init__(self):
        self.nodes = {}
        self.links = {}
        self.loads = {}

    @staticmethod
    def contacts(cand, placements):
        contacts = []
        for p in placements:
            if p['z'] >= cand['z'] or abs(p['z'] + p['dz'] - cand['z']) > .001:
                continue
            ox = min(p['x']+p['dx'], cand['x']+cand['dx'])-max(p['x'], cand['x'])
            oy = min(p['y']+p['dy'], cand['y']+cand['dy'])-max(p['y'], cand['y'])
            if ox > 1e-4 and oy > 1e-4:
                contacts.append((id(p), ox*oy))
        area = sum(a for _, a in contacts)
        return [(key, a/area) for key, a in contacts] if area else []

    def increments(self, cand, placements):
        links = self.contacts(cand, placements)
        pending = {}
        for key, fraction in links:
            pending[key] = pending.get(key, 0.) + cand.get('weight_kg', 0.)*fraction
        # 严格沿高度递减传播，先合并所有上游分支，避免重复计重。
        delta = {}
        while pending:
            key = max(pending, key=lambda k: self.nodes[k]['z'])
            weight = pending.pop(key)
            delta[key] = weight
            for lower, fraction in self.links[key]:
                pending[lower] = pending.get(lower, 0.) + weight*fraction
        return links, delta

    def permits(self, cand, placements, catalog):
        links, delta = self.increments(cand, placements)
        for key, extra in delta.items():
            p = self.nodes[key]
            sku = catalog.get(p['sku_id'])
            if sku is None:
                continue
            if not getattr(sku, 'allow_stacking_on_top', True):
                return False
            load = self.loads[key] + extra
            limit = getattr(sku, 'max_bearing_kg', None)
            pressure = getattr(sku, 'max_pressure_kg_m2', None)
            if limit is not None and load > limit + 1e-4:
                return False
            if pressure is not None and load/(p['dx']*p['dy']) > pressure + 1e-4:
                return False
        return True

    def commit(self, cand, placements):
        links, delta = self.increments(cand, placements)
        key = id(cand)
        self.nodes[key] = cand
        self.links[key] = links
        self.loads[key] = 0.
        for lower, extra in delta.items():
            self.loads[lower] += extra

    def rebuild(self, placements):
        self.__init__()
        built = []
        for p in sorted(placements, key=lambda p: p['z']):
            self.commit(p, built)
            built.append(p)
