"""商业化通用货单智能解析引擎入口。

用途:
    提供 parse_manifest_bytes 主函数，串联 Sheet 探测、表头定位、
    多维列映射、规则语义翻译及异常自愈校验。

输入/输出:
    输入原始文件字节流、文件名、可选目标柜型及用户覆盖映射/单位；
    输出包含 sheets、columns、mapping、items、accessory_rows、summary 的完整字典。

被谁调用:
    backend.server (POST /api/v1/manifest/parse), tests/test_manifest_importer.py
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from .anomaly_healer import heal_and_build_manifest
from .column_mapper import map_columns
from .sheet_detector import load_spreadsheet


CONTAINER_DIMS_MAP: Dict[str, Tuple[float, float, float]] = {
    "20GP": (5.898, 2.352, 2.393),
    "40GP": (12.032, 2.352, 2.393),
    "40HQ": (12.032, 2.352, 2.698),
    "45HQ": (13.556, 2.352, 2.698),
}


def parse_manifest_bytes(
    raw_bytes: bytes,
    filename: str,
    container_type: str = "40HQ",
    sheet_name: Optional[str] = None,
    override_mapping: Optional[Dict[str, Optional[str]]] = None,
    override_units: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """解析任意格式客户货单文件并返回标准化清单与体检报告。"""
    cont_dims = CONTAINER_DIMS_MAP.get((container_type or "40HQ").upper(), CONTAINER_DIMS_MAP["40HQ"])
    sheet_res = load_spreadsheet(raw_bytes, filename, sheet_name=sheet_name)
    headers = sheet_res["headers"]
    data_rows = sheet_res["data_rows"]

    mapping = map_columns(
        headers=headers,
        rows=data_rows,
        override_mapping=override_mapping,
        override_units=override_units,
    )
    healed = heal_and_build_manifest(
        headers=headers,
        rows=data_rows,
        mapping=mapping,
        container_dims=cont_dims,
    )

    return {
        "status": "ok",
        "filename": filename,
        "container_type": container_type,
        "sheets": sheet_res["sheets"],
        "selected_sheet": sheet_res["selected_sheet"],
        "header_row_1based": sheet_res["header_row_1based"],
        "columns": headers,
        "mapping": mapping,
        "ignored_summary_rows": sheet_res["ignored_summary_rows"],
        "accessory_rows": healed["accessory_rows"],
        "items": healed["items"],
        "summary": healed["summary"],
    }


__all__ = ["parse_manifest_bytes", "CONTAINER_DIMS_MAP"]
