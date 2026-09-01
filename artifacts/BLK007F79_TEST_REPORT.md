# BLK-007F-7.9 Test Report

## 专项测试

MSWALL-001～012：12/12 PASS。

覆盖内容：多 SKU 联合区域、单 SKU 不强制混合、侧边锚定、几何问题检测、同 SKU 层数语义、显式承压拒绝、确定性回放、支撑不足拒绝、库存门禁、候选完整验证、门墙不可变、方向权限不扩张。

## 全量回归

- Python：349/349 PASS，202.227s（包含后续 3DLAYER-001～005）。
- Frontend Node：18/18 PASS。
- 总计：367/367 PASS。
- 既有测试未修改为降低验收标准。

## 真实 14-SKU

- GlobalValidator：VALID
- overlap：0
- penetration：0
- OOB：0
- Door transport：PASS
- Door open：PASS
- utilization：77.68934770308941%
- deterministic layout fingerprint：`20c99c8491db3289e1065ec6c11b38065d0c4b38914279a64363f63080c8e5d9`

## 仍保留的质量问题

修正验收后，问题区域从只覆盖前5.84m改为覆盖0～11.424m。墙侧空隙从0.051m降到0；新增21个跨SKU支撑行和54件上层货物；不完整层56→51；多SKU墙10→14。仍有51个不完整层需要更深的三维交换式重建，因此本轮不再标记完整PASS。
