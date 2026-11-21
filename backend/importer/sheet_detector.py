"""多 Sheet 探测、合并单元格展开与动态表头行定位模块。

用途:
    读取客户上传的 .xlsx / .csv / .txt 文件，自动跳过汇总/校验报告页，
    选中最可能是货单明细的工作表，并容忍前 N 行公司抬头、空行与合并单元格，
    精确识别真正的表头行及数据起止行。

输入/输出:
    输入原始文件字节流与文件名；
    输出 Sheet 列表、选中 Sheet 名称、表头列表、数据行与被剔除的汇总/说明行。

被谁调用:
    backend.importer.__init__
"""
from __future__ import annotations

import csv
import io
import re
from typing import Any, Dict, List, Optional, Tuple

import openpyxl

from .cell_sanitizer import is_grand_summary_row_text, is_summary_row_text, normalize_text


NON_DETAIL_SHEET_RE = re.compile(
    r"(校验|报告|汇总|总结|说明|目录|封面|summary|report|readme|note|check|log)",
    re.IGNORECASE,
)

HEADER_HINT_RE = re.compile(
    r"(品名|产品|货物|名称|sku|货号|长|宽|高|尺寸|体积|cbm|毛重|净重|重量|箱数|件数|数量|要求|备注|"
    r"name|desc|length|width|height|size|dim|vol|weight|gw|nw|ctn|carton|qty|quantity|remark)",
    re.IGNORECASE,
)


def _expand_xlsx_sheet(ws) -> List[List[Any]]:
    """展开 openpyxl 工作表并填充合并单元格左上角值。"""
    max_r = min(ws.max_row or 0, 5000)
    max_c = min(ws.max_column or 0, 60)
    grid: List[List[Any]] = []
    for r in range(1, max_r + 1):
        row = [ws.cell(r, c).value for c in range(1, max_c + 1)]
        grid.append(row)

    for rng in ws.merged_cells.ranges:
        if rng.min_row > max_r or rng.min_col > max_c:
            continue
        top_val = grid[rng.min_row - 1][rng.min_col - 1]
        # 只对跨列不大的表头或分组标识向下/向右展开，避免大块说明区污染数据行
        if (rng.max_row - rng.min_row) <= 5 and (rng.max_col - rng.min_col) <= 5:
            for r in range(rng.min_row, min(rng.max_row, max_r) + 1):
                for c in range(rng.min_col, min(rng.max_col, max_c) + 1):
                    if grid[r - 1][c - 1] is None:
                        grid[r - 1][c - 1] = top_val
    return grid


def _read_csv_bytes(raw_bytes: bytes) -> List[List[Any]]:
    """兼容 UTF-8 / UTF-8-SIG / GBK 编码解析 CSV/TSV。"""
    text = None
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk", "latin1"):
        try:
            text = raw_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw_bytes.decode("utf-8", errors="replace")

    sample = text[:2048]
    delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [row for row in reader]


def _score_sheet_rows(name: str, rows: List[List[Any]]) -> float:
    """为工作表计算成为主货单明细页的置信度分数。"""
    if not rows:
        return -100.0
    score = 0.0
    if NON_DETAIL_SHEET_RE.search(name):
        score -= 40.0
    non_empty_rows = [r for r in rows if any(normalize_text(v) for v in r)]
    if len(non_empty_rows) < 2:
        return -50.0
    score += min(len(non_empty_rows), 100) * 0.4

    # 检查前 15 行是否包含典型货单表头关键词
    best_hdr_hits = 0
    for r in non_empty_rows[:15]:
        hits = sum(1 for v in r if HEADER_HINT_RE.search(normalize_text(v)))
        best_hdr_hits = max(best_hdr_hits, hits)
    score += best_hdr_hits * 8.0
    return score


def detect_header_row(rows: List[List[Any]]) -> int:
    """扫描前 20 行，找出最可能是表头行的 0-based 索引。"""
    best_idx = 0
    best_score = -1e9
    scan_limit = min(len(rows), 20)
    for idx in range(scan_limit):
        row = rows[idx]
        non_empty = [normalize_text(v) for v in row if normalize_text(v)]
        if len(non_empty) < 2:
            continue
        str_cnt = sum(1 for t in non_empty if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", t))
        hint_hits = sum(1 for t in non_empty if HEADER_HINT_RE.search(t))
        # 下一行是否存在数字列（表头下方通常是明细数据）
        next_num_bonus = 0.0
        if idx + 1 < len(rows):
            next_vals = [normalize_text(v) for v in rows[idx + 1] if normalize_text(v)]
            num_cnt = sum(1 for t in next_vals if re.search(r"\d", t))
            next_num_bonus = min(num_cnt, 6) * 1.5
        sc = hint_hits * 10.0 + str_cnt * 1.5 + next_num_bonus - idx * 0.3
        if sc > best_score:
            best_score = sc
            best_idx = idx
    return best_idx


def load_spreadsheet(
    raw_bytes: bytes,
    filename: str,
    sheet_name: Optional[str] = None,
) -> Dict[str, Any]:
    """加载表格并自动选页、定位表头与分离汇总/空行。"""
    ext = (filename or "").lower().rsplit(".", 1)[-1] if "." in (filename or "") else ""
    sheets_data: Dict[str, List[List[Any]]] = {}

    if ext in ("csv", "tsv", "txt"):
        sheets_data["CSV"] = _read_csv_bytes(raw_bytes)
    else:
        wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=True)
        for sname in wb.sheetnames:
            sheets_data[sname] = _expand_xlsx_sheet(wb[sname])

    sheet_names = list(sheets_data.keys())
    if not sheet_names:
        raise ValueError("文件中不包含任何可读工作表")

    if sheet_name and sheet_name in sheets_data:
        selected_sheet = sheet_name
    else:
        selected_sheet = max(sheet_names, key=lambda n: _score_sheet_rows(n, sheets_data[n]))

    raw_rows = sheets_data[selected_sheet]
    hdr_idx = detect_header_row(raw_rows) if raw_rows else 0
    raw_headers = raw_rows[hdr_idx] if hdr_idx < len(raw_rows) else []

    # 裁剪尾部全空列，保留唯一列名
    last_non_empty_col = 0
    for c_idx, h in enumerate(raw_headers):
        if normalize_text(h):
            last_non_empty_col = c_idx + 1
    for r in raw_rows[hdr_idx + 1 : hdr_idx + 20]:
        for c_idx, v in enumerate(r):
            if normalize_text(v) and c_idx + 1 > last_non_empty_col:
                last_non_empty_col = c_idx + 1

    headers: List[str] = []
    seen_names: Dict[str, int] = {}
    for c_idx in range(last_non_empty_col):
        base = normalize_text(raw_headers[c_idx]) if c_idx < len(raw_headers) else ""
        if not base:
            base = f"列{c_idx + 1}"
        if base in seen_names:
            seen_names[base] += 1
            base = f"{base}_{seen_names[base]}"
        else:
            seen_names[base] = 1
        headers.append(base)

    data_rows: List[Tuple[int, List[Any]]] = []
    ignored_summary_rows: List[Dict[str, Any]] = []

    for r_idx in range(hdr_idx + 1, len(raw_rows)):
        row = raw_rows[r_idx][:last_non_empty_col]
        if len(row) < len(headers):
            row = row + [None] * (len(headers) - len(row))
        texts = [normalize_text(v) for v in row]
        if not any(texts):
            continue
        # 若前6列任意出现“合计/总计/共计/Total”，归入忽略列表
        if any(is_summary_row_text(t) for t in texts[:6]):
            ignored_summary_rows.append({
                "excel_row": r_idx + 1,
                "reason": "汇总/合计行已自动跳过",
                "preview": " | ".join(t for t in texts if t)[:120],
            })
            # 若已解析出有效数据行且遇到整表终结性总计/共计/合计行（非小计），截断后续附表与页脚签名区
            if data_rows and any(is_grand_summary_row_text(t) for t in texts[:6]):
                trailing_rows = [
                    (tr_idx + 1, [normalize_text(v) for v in raw_rows[tr_idx]])
                    for tr_idx in range(r_idx + 1, len(raw_rows))
                ]
                trailing_non_empty = [(rn, tr) for rn, tr in trailing_rows if any(tr)]
                if trailing_non_empty:
                    first_rn, first_tr = trailing_non_empty[0]
                    ignored_summary_rows.append({
                        "excel_row": first_rn,
                        "reason": f"总计行后检测到 {len(trailing_non_empty)} 行附表/页脚/签字栏内容，已自动截断",
                        "preview": " | ".join(t for t in first_tr if t)[:120],
                    })
                break
            continue
        data_rows.append((r_idx + 1, row))

    return {
        "sheets": sheet_names,
        "selected_sheet": selected_sheet,
        "header_row_1based": hdr_idx + 1,
        "headers": headers,
        "data_rows": data_rows,
        "ignored_summary_rows": ignored_summary_rows,
    }
