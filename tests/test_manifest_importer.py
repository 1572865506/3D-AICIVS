"""商业化通用货单智能解析引擎单元测试。"""
from __future__ import annotations

import io
import os
import openpyxl
import pytest

from backend.importer import parse_manifest_bytes


REAL_EXCEL_PATH = "/Users/anthony/Downloads/确认更-20260914智慧_预计9.19装柜_合并.xlsx"


def _make_xlsx_bytes(sheets: dict[str, list[list]]) -> bytes:
    wb = openpyxl.Workbook()
    first = True
    for name, rows in sheets.items():
        ws = wb.active if first else wb.create_sheet(title=name)
        ws.title = name
        first = False
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.mark.skipif(not os.path.exists(REAL_EXCEL_PATH), reason="真实测试货单不在本机")
def test_real_81sku_excel_manifest_parse():
    with open(REAL_EXCEL_PATH, "rb") as f:
        raw = f.read()
    res = parse_manifest_bytes(raw, "确认更-20260914智慧_预计9.19装柜_合并.xlsx", container_type="40HQ")
    assert res["selected_sheet"] == "预计9.19装柜"
    assert res["summary"]["sku_count"] == 81
    assert res["summary"]["total_cartons"] == 1940
    assert abs(res["summary"]["total_weight_kg"] - 13841.9) < 2.0
    assert 76.5 <= res["summary"]["total_cbm"] <= 77.2
    assert res["summary"]["can_submit"] is True
    assert res["mapping"]["cartons"]["source_col"] == "产品箱数(箱)"
    assert res["mapping"]["unit_weight"]["source_col"] == "单箱毛重(KG)"
    door_items = [it for it in res["items"] if it["placement_rules"]["is_door_stopper"]]
    assert len(door_items) == 5


def test_dirty_manifest_healing_and_blocking():
    raw = _make_xlsx_bytes({
        "汇总说明": [["说明", "不要选我"], ["总计", 100]],
        "出货明细": [
            ["XX科技有限公司 2026 装箱单", None, None, None, None, None, None, None],
            [],
            ["品名", "长(m)", "宽(m)", "高(m)", "单箱重(kg)", "箱数", "体积CBM", "摆放要求"],
            # 1. 正常行 + 中文规则
            ["标准电源箱", 0.5, 0.4, 0.3, 12.0, 10, 0.6, "不可压，正立，最多堆3层"],
            # 2. 行级隐形 cm 漂移（表头是 m，但数值是 56/28/36 + 原表 CBM 吻合）
            ["隐形cm行", 56, 28, 36, "670g", 10, 0.564, "最后放"],
            # 3. 缺失高 + 缺失重量 + 小数箱数
            ["缺高缺重行", 0.6, 0.4, "", "", 9.85, 1.2, "放底层"],
            # 4. 0箱配件附带行
            ["随箱附带线材", 0.2, 0.1, 0.1, 0.5, 0, 0, "随主箱附带"],
            # 5. 物理超柜尺寸无法修复（BLOCKED）
            ["超长钢架", 15.0, 3.5, 3.2, 500, 1, 168.0, "—"],
            # 6. 表尾合计行应被自动忽略
            ["合计", None, None, None, None, 31, 170.36, None],
        ],
    })
    res = parse_manifest_bytes(raw, "dirty_test.xlsx", container_type="40HQ")
    assert res["selected_sheet"] == "出货明细"
    assert res["header_row_1based"] == 3
    assert len(res["ignored_summary_rows"]) == 1
    assert len(res["accessory_rows"]) == 1
    assert len(res["items"]) == 4

    it0, it1, it2, it3 = res["items"]
    assert it0["status"] == "OK"
    assert it0["placement_rules"]["allow_stacking_on_top"] is False
    assert it0["placement_rules"]["upright_only"] is True
    assert it0["placement_rules"]["max_stack_layers"] == 3

    # 行级 cm 漂移自动纠偏 + 670g 自动折算为 0.67kg + 最后放
    assert it1["d"] == 0.56 and it1["w"] == 0.28 and it1["h"] == 0.36
    assert abs(it1["weight"] - 0.67) < 1e-3
    assert it1["placement_rules"]["is_door_stopper"] is True
    assert it1["status"] in ("AUTO_FIXED", "NEED_CONFIRM")

    # 缺高反推 + 小数向上取整 10 + 缺失重量非零估算
    assert it2["quantity"] == 10
    assert it2["h"] > 0.1
    assert it2["weight"] > 0.0
    assert it2["placement_rules"]["must_be_on_floor"] is True

    # 超长钢架阻断
    assert it3["status"] == "BLOCKED"
    assert res["summary"]["can_submit"] is False


def test_compound_dims_and_total_weight_csv():
    csv_text = (
        "SKU,Description,Dimensions,Cartons,Total G.W.(kg),Remark\n"
        "A01,Monitor Box,560x280x360mm,20,300,door\n"
        "A02,Keyboard,40*30*20cm,10,50,fragile\n"
    ).encode("utf-8")
    res = parse_manifest_bytes(csv_text, "packing_list.csv", container_type="40HQ")
    assert res["summary"]["sku_count"] == 2
    assert res["summary"]["total_cartons"] == 30
    assert res["summary"]["can_submit"] is True
    it0, it1 = res["items"]
    assert (it0["d"], it0["w"], it0["h"]) == (0.56, 0.28, 0.36)
    assert abs(it0["weight"] - 15.0) < 1e-3
    assert it0["placement_rules"]["is_door_stopper"] is True
    assert (it1["d"], it1["w"], it1["h"]) == (0.4, 0.3, 0.2)
    assert abs(it1["weight"] - 5.0) < 1e-3
    assert it1["placement_rules"]["allow_stacking_on_top"] is False


def test_real_singpc_raw_dirty_csv_manifest_parse():
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "singpc_1126_raw.csv")
    with open(fixture_path, "rb") as f:
        raw = f.read()

    res = parse_manifest_bytes(raw, "singpc_1126_raw.csv", container_type="20GP")

    # 1. 表头定位与多表混排/页脚截断校验（序号1~12+共计行之后为生产要求清单与签字区，必须截断）
    assert res["header_row_1based"] == 2
    assert len(res["ignored_summary_rows"]) == 2
    assert "共计" in res["ignored_summary_rows"][0]["preview"]
    assert "自动截断" in res["ignored_summary_rows"][1]["reason"]

    # 2. 残缺样品行（序号12 VGA样品：无件数/无重量/无体积）应优雅跳过并归入 accessory_rows
    assert len(res["accessory_rows"]) == 1
    assert "VGA 样品" in res["accessory_rows"][0]["name"]

    # 3. 汇总指标勾稽校验：13个有效装箱SKU，总计 266 件，总体积 29.355 m³，可提交
    summary = res["summary"]
    assert summary["sku_count"] == 13
    assert summary["total_cartons"] == 266
    assert abs(summary["total_cbm"] - 29.355) < 0.01
    assert abs(summary["total_weight_kg"] - 4001.55) < 0.1
    assert summary["blocked_count"] == 0
    assert summary["can_submit"] is True

    # 4. 列映射消歧校验：箱数列必须选中“件数”(266)而非“数量”(2269套)
    assert res["mapping"]["cartons"]["source_col"] == "件数"
    assert res["mapping"]["unit_cbm"]["source_col"] == "体积"
    assert res["mapping"]["cbm"]["source_col"] == "总体积"

    # 5. 全维缺失体积反推、合并续行继承、毛重微差告警与物流备注不误判
    items = res["items"]
    assert all(it["inferred_dimensions"] is True for it in items)
    assert all(
        any(iss["code"] == "INFERRED_DIMS_FROM_VOLUME" for iss in it["issues"])
        for it in items
    )

    # 合并续行（第11行，序号9下方空品名续行 300套/1件/2.25kg/0.017391m³）
    merged_item = items[9]
    assert merged_item["quantity"] == 1
    assert abs(merged_item["weight"] - 2.25) < 1e-3
    assert "WIFI 6" in merged_item["name"] and "(续)" in merged_item["name"]
    assert any(iss["code"] == "INHERITED_MERGED_ROW" for iss in merged_item["issues"])

    # 序号8（15.6寸笔记本：单箱重12.45 vs 总毛重11）稳健处理并告警，备注“明天拉过去”不误判为摆放约束
    row8_item = items[7]
    assert abs(row8_item["weight"] - 12.45) < 1e-3
    assert any(iss["code"] == "WEIGHT_TOTAL_MISMATCH" for iss in row8_item["issues"])
    assert row8_item["logistics_note"] == "明天拉过去"
    assert row8_item["rule_tags"] == []
    assert row8_item["placement_rules"]["is_door_stopper"] is False
    assert row8_item["placement_rules"]["must_be_on_floor"] is False

