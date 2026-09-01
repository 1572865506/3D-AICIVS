# BLK-007F-8B Repair Test Report

## 专项测试

- F8B-001：未满宽货墙保持贴侧，不居中切出双侧缝隙。
- F8B-002：禁止机会式单箱提交；只接受结构化地面行或顶部行。
- F8B-003：墙接口修复启用且单列移动上限受控。
- F8B-004：不增加任何方向权限，支撑率继续满足原约束。
- F8B-005：14-SKU布局保持物理合法且不低于稳定基线。
- F8B-006：混合SKU能够形成100%覆盖的原子顶部行。
- F8B-007：单个突出箱只修复相邻肩部列，不推动整墙。
- F8B-008：中心障碍不会毒化整条地面行，左右肩部独立形成完整货排。
- F8B-009：多个相邻下层箱体的顶面可以联合支撑一条完整上层货排。
- Validator：SKU自身层数限制不再错误禁止合法异SKU顶载。

专项F8B测试：`9/9 PASS`；层数语义专项测试PASS。

## 全量回归

- Python：`332/332 PASS`，耗时 `219.598s`。
- Frontend Node：`8/8 PASS`。
- 合计：`340 PASS / 0 FAIL`。
- Collision、Support、Compression、Orientation、Door及GlobalValidator均未关闭或放宽。
