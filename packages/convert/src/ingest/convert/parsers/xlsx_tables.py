"""Bảng trong xlsx thành Markdown sạch, thay cho MarkItDown (pandas).

MarkItDown đọc cả sheet thành một DataFrame: ô trống thành NaN, cột không tiêu đề thành
"Unnamed: N", và các bảng đặt cạnh nhau trên cùng sheet bị trộn vào nhau. Ở đây mỗi
vùng ô liền nhau (kể cả chéo) là một bảng riêng, chỉ lấy các cột/dòng của vùng đó.

- Vùng một dòng hoặc một cột thành văn bản ("Thuế suất VAT: 0.1"), không thành bảng.
- Dòng đầu là tiêu đề nếu đủ ô và toàn chữ (cho phép số dạng năm như 2024). Không có
  tiêu đề mà cột đầu là nhãn (Tổng, Trung bình) thì mỗi dòng thành "nhãn: giá trị";
  còn lại đặt tiêu đề theo tên cột (A, B...).
- Giá trị lấy từ cache của file (data_only). Ô công thức chưa có cache để trống,
  công thức đã có ở phần "Công thức trong file".
"""

from __future__ import annotations

import datetime as dt
import io
import logging

logger = logging.getLogger(__name__)

MAX_CELLS = 1_000_000  # quá mức này trả "" để quay về MarkItDown


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() and abs(v) < 1e15 else f"{v:.10g}"
    if isinstance(v, dt.datetime):
        return v.date().isoformat() if v.time() == dt.time() else v.isoformat(sep=" ")
    if isinstance(v, dt.date | dt.time):
        return v.isoformat()
    s = str(v).strip()
    return "" if s.startswith("#") and s.endswith(("!", "?", "/0", "N/A")) else s  # #REF!...


def _cell(v: str) -> str:
    return v.replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _col_letter(idx: int) -> str:
    s = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        s = chr(65 + rem) + s
    return s


def find_regions(cells: dict[tuple[int, int], str]) -> list[list[tuple[int, int]]]:
    """Gom ô có giá trị thành các vùng liền nhau (8 hướng), thứ tự theo góc trên trái.

    Hai vùng có khung bao chồng nhau được gộp, để bảng có ô trống lẻ không bị cắt đôi.
    """
    parent = {k: k for k in cells}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for r, c in cells:
        for dr, dc in ((0, 1), (1, -1), (1, 0), (1, 1)):
            n = (r + dr, c + dc)
            if n in cells:
                union((r, c), n)

    groups: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for k in cells:
        groups.setdefault(find(k), []).append(k)
    regions = list(groups.values())

    merged = True
    while merged and len(regions) > 1:
        merged = False
        boxes = [_bbox(g) for g in regions]
        for i in range(len(regions)):
            for j in range(i + 1, len(regions)):
                if _overlap(boxes[i], boxes[j]):
                    regions[i] = regions[i] + regions[j]
                    del regions[j]
                    merged = True
                    break
            if merged:
                break
    regions.sort(key=lambda g: (_bbox(g)[0], _bbox(g)[1]))
    return regions


def _bbox(region) -> tuple[int, int, int, int]:
    rows = [r for r, _ in region]
    cols = [c for _, c in region]
    return min(rows), min(cols), max(rows), max(cols)


def _overlap(a, b) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _is_number(s: str) -> bool:
    try:
        float(s.replace(",", ""))
        return True
    except ValueError:
        return False


def _header_like(v: str) -> bool:
    """Ô có thể là tiêu đề cột: chữ, hoặc số dạng năm (2024, 2025)."""
    if not _is_number(v):
        return True
    return v.isdigit() and 1900 <= int(v) <= 2100


def region_markdown(cells: dict[tuple[int, int], str], region) -> str:
    r1, c1, r2, c2 = _bbox(region)
    own = set(region)
    grid = [
        [cells[(r, c)] if (r, c) in own else "" for c in range(c1, c2 + 1)]
        for r in range(r1, r2 + 1)
    ]
    # bỏ cột trống hoàn toàn (ô chỉ thuộc vùng khác)
    keep = [j for j in range(len(grid[0])) if any(row[j] for row in grid)]
    grid = [[row[j] for j in keep] for row in grid]
    cols = [c1 + j for j in keep]

    if len(grid) == 1:  # một dòng: "nhãn: giá trị" hoặc nối bằng " | "
        vals = [v for v in grid[0] if v]
        return f"{vals[0]}: {vals[1]}" if len(vals) == 2 else " | ".join(vals)
    if len(cols) == 1:  # một cột: mỗi ô một dòng, cặp nhãn trên giá trị dưới thì gộp
        vals = [row[0] for row in grid if row[0]]
        if len(vals) == 2 and not _is_number(vals[0]):
            return f"{vals[0]}: {vals[1]}"
        return "\n".join(vals)

    first = grid[0]
    if all(first) and all(_header_like(v) for v in first) and not _is_number(first[0]):
        header, body = first, grid[1:]
    elif all(row[0] and not _is_number(row[0]) for row in grid):
        # không có tiêu đề, cột đầu là nhãn (Tổng, Trung bình...): mỗi dòng "nhãn: giá trị"
        return "\n".join(f"{row[0]}: " + " | ".join(v for v in row[1:] if v) for row in grid)
    else:
        header, body = [_col_letter(c) for c in cols], grid
    lines = [
        "| " + " | ".join(_cell(h) for h in header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in body:
        if any(row):
            lines.append("| " + " | ".join(_cell(v) for v in row) + " |")
    where = f"{_col_letter(c1)}{r1 + 1}:{_col_letter(c2)}{r2 + 1}"
    return f"Bảng {where}:\n\n" + "\n".join(lines)


def _sheet_cells(ws) -> dict[tuple[int, int], str] | None:
    cells: dict[tuple[int, int], str] = {}
    for r, row in enumerate(ws.iter_rows(values_only=True)):
        for c, v in enumerate(row):
            s = _text(v)
            if s:
                cells[(r, c)] = s
                if len(cells) > MAX_CELLS:
                    return None
    return cells


def workbook_markdown(data: bytes) -> str:
    """Toàn bộ sheet thành Markdown. Lỗi hoặc file quá lớn trả "" để dùng MarkItDown."""
    try:
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    except Exception:
        logger.warning("openpyxl không mở được xlsx; dùng MarkItDown.", exc_info=True)
        return ""
    sections: list[str] = []
    try:
        for ws in wb.worksheets:
            if not hasattr(ws, "iter_rows"):  # chartsheet
                continue
            cells = _sheet_cells(ws)
            if cells is None:
                logger.warning("Sheet %s quá lớn; dùng MarkItDown.", ws.title)
                return ""
            parts = [region_markdown(cells, g) for g in find_regions(cells)]
            body = "\n\n".join(p for p in parts if p)
            sections.append(f"## {ws.title}" + (f"\n\n{body}" if body else ""))
    except Exception:
        logger.warning("Lỗi khi đọc bảng xlsx; dùng MarkItDown.", exc_info=True)
        return ""
    finally:
        wb.close()
    return "\n\n".join(sections).strip()
