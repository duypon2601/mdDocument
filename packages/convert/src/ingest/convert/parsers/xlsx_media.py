"""Ảnh và biểu đồ nhúng trong xlsx, phần MarkItDown bỏ qua.

- Biểu đồ gốc của Excel (`xl/charts/chartN.xml`) có sẵn dữ liệu trong cache của XML,
  nên đọc thẳng ra bảng Markdown, không cần OCR hay Vision LLM. Cache trống thì đọc
  vùng ô mà công thức `c:f` trỏ tới bằng openpyxl.
- Ảnh (`xl/media/*`) được liệt kê theo thứ tự sheet và vị trí neo, để activity
  `ocr_pages` lấy ảnh thứ i giống hệt lúc `detect_format` đếm. Ảnh đi chung đường
  OCR/Vision LLM với ảnh trong docx (`ConvertActivities._read_image`).

Đi theo quan hệ: workbook -> sheet -> drawing -> (ảnh | chart). Ảnh không gắn với
drawing nào vẫn được lấy, sheet để trống.
"""

from __future__ import annotations

import io
import logging
import posixpath
import re
import zipfile
from dataclasses import dataclass

from defusedxml import ElementTree as ET

logger = logging.getLogger(__name__)

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
}
_R_EMBED = f"{{{NS['r']}}}embed"
_R_ID = f"{{{NS['r']}}}id"

# Ảnh raster; EMF/WMF là ảnh vector, thường là logo. Đọc ra PNG bằng docx_images.read_png.
IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff"}
MIN_IMAGE_BYTES = 2048  # nhỏ hơn thường là icon, OCR không ra gì
MAX_IMAGE_BYTES = 20 * 1024 * 1024  # chặn ảnh giải nén quá lớn
MAX_IMAGES = 200

CHART_KIND_VI = {
    "bar": "cột/thanh", "line": "đường", "pie": "tròn", "doughnut": "vành khuyên",
    "area": "vùng", "scatter": "phân tán", "radar": "radar", "bubble": "bong bóng",
    "stock": "chứng khoán", "surface": "bề mặt", "ofPie": "tròn tách",
}  # fmt: skip


@dataclass
class Embedded:
    """Một ảnh hoặc chart neo trong sheet."""

    path: str  # đường dẫn trong zip, ví dụ xl/media/image1.png
    sheet: str = ""
    anchor: str = ""  # ô góc trên trái, ví dụ B3

    @property
    def ext(self) -> str:
        return self.path.rsplit(".", 1)[-1].lower() if "." in self.path else ""

    def label(self) -> str:
        where = [f"sheet {self.sheet}"] if self.sheet else []
        if self.anchor:
            where.append(f"ô {self.anchor}")
        return ", ".join(where)


# ---------- đọc cấu trúc gói ----------


def _xml(z: zipfile.ZipFile, name: str):
    try:
        return ET.fromstring(z.read(name))
    except KeyError:
        return None


def _rels(z: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str]]:
    """rId -> (đường dẫn đích trong zip, kiểu quan hệ) của một part."""
    folder, base = posixpath.split(part)
    root = _xml(z, posixpath.join(folder, "_rels", base + ".rels"))
    if root is None:
        return {}
    out = {}
    for rel in root.findall("pr:Relationship", NS):
        if rel.get("TargetMode") == "External":
            continue
        target = rel.get("Target", "")
        if target.startswith("/"):
            path = target.lstrip("/")
        else:
            path = posixpath.normpath(posixpath.join(folder, target))
        out[rel.get("Id", "")] = (path, rel.get("Type", "").rsplit("/", 1)[-1])
    return out


def _sheets(z: zipfile.ZipFile) -> list[tuple[str, str]]:
    """[(tên sheet, part)] theo thứ tự trong workbook, gồm cả chartsheet."""
    wb = _xml(z, "xl/workbook.xml")
    if wb is None:
        return []
    rels = _rels(z, "xl/workbook.xml")
    out = []
    for sh in wb.findall("m:sheets/m:sheet", NS):
        target = rels.get(sh.get(_R_ID, ""))
        if target:
            out.append((sh.get("name", ""), target[0]))
    return out


def _col_letter(idx: int) -> str:
    s = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        s = chr(65 + rem) + s
    return s


def _anchor_cell(anchor) -> str:
    frm = anchor.find("xdr:from", NS)
    if frm is None:
        return ""
    try:
        col = int(frm.findtext("xdr:col", "0", NS))
        row = int(frm.findtext("xdr:row", "0", NS))
    except ValueError:
        return ""
    return f"{_col_letter(col)}{row + 1}"


def _scan(z: zipfile.ZipFile) -> tuple[list[Embedded], list[Embedded]]:
    """(ảnh, chart) theo thứ tự sheet rồi thứ tự neo trong drawing."""
    images: list[Embedded] = []
    charts: list[Embedded] = []
    seen: set[str] = set()
    for sheet_name, sheet_part in _sheets(z):
        for drawing, kind in _rels(z, sheet_part).values():
            if kind != "drawing":
                continue
            root = _xml(z, drawing)
            if root is None:
                continue
            drels = _rels(z, drawing)
            for anchor in root:
                cell = _anchor_cell(anchor)
                for blip in anchor.iter(f"{{{NS['a']}}}blip"):
                    target = drels.get(blip.get(_R_EMBED, ""))
                    if target and target[0] not in seen:
                        seen.add(target[0])
                        images.append(Embedded(target[0], sheet_name, cell))
                for ch in anchor.iter(f"{{{NS['c']}}}chart"):
                    target = drels.get(ch.get(_R_ID, ""))
                    if target:
                        charts.append(Embedded(target[0], sheet_name, cell))
    # ảnh không gắn drawing (đặt ở header, kéo thả lạ...) vẫn giữ lại
    for name in sorted(z.namelist()):
        if name.startswith("xl/media/") and name not in seen:
            images.append(Embedded(name))
    return images, charts


def _open(data: bytes) -> zipfile.ZipFile | None:
    try:
        return zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return None


# ---------- ảnh ----------


def list_images(data: bytes, min_bytes: int = MIN_IMAGE_BYTES) -> list[Embedded]:
    """Ảnh OCR được, thứ tự cố định với cùng một file. File lỗi trả []."""
    z = _open(data)
    if z is None:
        return []
    try:
        images, _ = _scan(z)
    except Exception:
        logger.warning("Không đọc được drawing trong xlsx; bỏ qua ảnh.", exc_info=True)
        return []
    out = []
    for img in images:
        if img.ext not in IMAGE_EXT:
            continue
        try:
            size = z.getinfo(img.path).file_size
        except KeyError:
            continue
        if min_bytes <= size <= MAX_IMAGE_BYTES:
            out.append(img)
    if len(out) > MAX_IMAGES:
        logger.warning("xlsx có %d ảnh, chỉ lấy %d ảnh đầu.", len(out), MAX_IMAGES)
        out = out[:MAX_IMAGES]
    return out


# ---------- biểu đồ ----------


def _texts(el) -> str:
    if el is None:
        return ""
    return "".join(t.text or "" for t in el.iter(f"{{{NS['a']}}}t")).strip()


def _cache_points(ref) -> list[str]:
    """Điểm dữ liệu trong strCache/numCache/strLit/numLit, đặt đúng chỉ số idx."""
    pts = ref.findall(".//c:pt", NS)
    if not pts:
        return []
    count_el = ref.find(".//c:ptCount", NS)
    try:
        n = int(count_el.get("val")) if count_el is not None else 0
    except (TypeError, ValueError):
        n = 0
    values: dict[int, str] = {}
    for pt in pts:
        try:
            values[int(pt.get("idx", "0"))] = (pt.findtext("c:v", "", NS) or "").strip()
        except ValueError:
            continue
    n = max(n, max(values) + 1 if values else 0)
    return [values.get(i, "") for i in range(n)]


class _CellResolver:
    """Đọc vùng ô cho công thức `'Sheet1'!$B$2:$B$5` khi chart không có cache."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._wb = None
        self._failed = False

    def values(self, formula: str) -> list[str]:
        if self._failed or not formula:
            return []
        try:
            from openpyxl.utils.cell import range_to_tuple

            if self._wb is None:
                from openpyxl import load_workbook

                self._wb = load_workbook(io.BytesIO(self._data), data_only=True, read_only=True)
            sheet, (c1, r1, c2, r2) = range_to_tuple(formula.strip().lstrip("("))
            ws = self._wb[sheet.strip("'")]
            rows = ws.iter_rows(min_row=r1, max_row=r2, min_col=c1, max_col=c2, values_only=True)
            return ["" if v is None else str(v) for row in rows for v in row]
        except Exception:
            logger.debug("Không đọc được vùng ô %s cho chart.", formula, exc_info=True)
            if self._wb is None:
                self._failed = True
            return []


def _ref_values(el, resolver: _CellResolver) -> list[str]:
    if el is None:
        return []
    multi = el.find("c:multiLvlStrRef", NS)
    if multi is not None:
        lvl = multi.find(".//c:lvl", NS)  # mức trong cùng là nhãn chi tiết nhất
        if lvl is not None:
            return _cache_points(lvl)
    for tag in ("numRef", "strRef"):
        ref = el.find(f"c:{tag}", NS)
        if ref is not None:
            return _cache_points(ref) or resolver.values(ref.findtext("c:f", "", NS))
    for tag in ("numLit", "strLit"):
        lit = el.find(f"c:{tag}", NS)
        if lit is not None:
            return _cache_points(lit)
    return []


def _series_name(ser, i: int, resolver: _CellResolver) -> str:
    tx = ser.find("c:tx", NS)
    if tx is not None:
        direct = tx.findtext("c:v", "", NS).strip()
        if direct:
            return direct
        vals = [v for v in _ref_values(tx, resolver) if v]
        if vals:
            return " ".join(vals)
    return f"Chuỗi {i}"


def _cell(v: str) -> str:
    return v.replace("|", "\\|").replace("\n", " ").strip()


def chart_markdown(root, resolver: _CellResolver, heading: str) -> str:
    """Một chart thành tiêu đề + bảng Markdown (hàng = hạng mục, cột = chuỗi)."""
    chart = root.find("c:chart", NS)
    plot = chart.find("c:plotArea", NS) if chart is not None else None
    if plot is None:
        return ""
    title = _texts(chart.find("c:title", NS))
    kinds: list[str] = []
    names: list[str] = []
    columns: list[list[str]] = []
    categories: list[str] = []
    for group in plot:
        tag = group.tag.rsplit("}", 1)[-1]
        if not tag.endswith("Chart"):
            continue
        kind = tag[: -len("Chart")].replace("3D", "")
        if kind not in kinds:
            kinds.append(kind)
        for ser in group.findall("c:ser", NS):
            cats = _ref_values(ser.find("c:cat", NS), resolver) or _ref_values(
                ser.find("c:xVal", NS), resolver
            )
            vals = _ref_values(ser.find("c:val", NS), resolver) or _ref_values(
                ser.find("c:yVal", NS), resolver
            )
            if len(cats) > len(categories):
                categories = cats
            names.append(_series_name(ser, len(names) + 1, resolver))
            columns.append(vals)
    if not columns:
        return ""

    axes = [_texts(ax.find("c:title", NS)) for ax in plot if ax.tag.endswith("Ax")]
    axes = [a for a in axes if a]
    head = f"### {heading}" + (f": {title}" if title else "")
    lines = [head, ""]
    info = ["Loại: " + ", ".join(CHART_KIND_VI.get(k, k) for k in kinds)]
    if axes:
        info.append("Trục: " + " / ".join(axes))
    lines += [". ".join(info) + ".", ""]

    n = max([len(categories)] + [len(c) for c in columns])
    header = ["Hạng mục"] + names
    lines.append("| " + " | ".join(_cell(h) for h in header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for i in range(n):
        cat = categories[i] if i < len(categories) else str(i + 1)
        row = [cat] + [c[i] if i < len(c) else "" for c in columns]
        lines.append("| " + " | ".join(_cell(v) for v in row) + " |")
    return "\n".join(lines)


def chart_part_markdown(z: zipfile.ZipFile, chart_path: str, heading: str) -> str:
    """Chart nằm trong docx/pptx (word/charts, ppt/charts): cùng định dạng XML với xlsx.

    Cache trống thì đọc vùng ô từ workbook nhúng kèm chart (quan hệ `package`).
    """
    root = _xml(z, chart_path)
    if root is None:
        return ""
    embedded = b""
    for path, kind in _rels(z, chart_path).values():
        if kind == "package" and path.endswith((".xlsx", ".xlsm")):
            try:
                embedded = z.read(path)
            except KeyError:
                continue
            break
    return chart_markdown(root, _CellResolver(embedded), heading)


def charts_markdown(data: bytes) -> str:
    """Toàn bộ chart trong file thành một phần Markdown. Không có chart trả ""."""
    z = _open(data)
    if z is None:
        return ""
    try:
        _, charts = _scan(z)
    except Exception:
        logger.warning("Không đọc được drawing trong xlsx; bỏ qua chart.", exc_info=True)
        return ""
    resolver = _CellResolver(data)
    parts = []
    for i, ch in enumerate(charts, 1):
        try:
            root = _xml(z, ch.path)
            if root is None:
                continue
            where = ch.label()
            heading = f"Biểu đồ {i}" + (f" ({where})" if where else "")
            md = chart_markdown(root, resolver, heading)
        except Exception:
            logger.warning("Chart %s lỗi; bỏ qua.", ch.path, exc_info=True)
            continue
        if md:
            parts.append(md)
    if not parts:
        return ""
    return "## Biểu đồ trong file\n\n" + "\n\n".join(parts)


# ---------- công thức ----------

MAX_FORMULA_ROWS = 500  # số dòng tối đa trong bảng công thức, sau khi đã gộp

# Tham chiếu ô kiểu A1/$B$2. Lookaround để không bắt nhầm tên hàm như LOG10( hay ATAN2(
_REF = re.compile(r"(?<![\w.])(\$?)([A-Z]{1,3})(\$?)(\d+)(?![\w(])")


def _pattern(formula: str, row: int) -> str:
    """Công thức với số dòng tương đối, để nhận ra công thức kéo xuống (fill down)."""

    def sub(m: re.Match) -> str:
        if m.group(3):  # dòng cố định $
            return m.group(0)
        return f"{m.group(1)}{m.group(2)}R[{int(m.group(4)) - row}]"

    return _REF.sub(sub, formula)


def _formula_text(value) -> str | None:
    if isinstance(value, str):
        return value if value.startswith("=") else None
    text = getattr(value, "text", None)  # ArrayFormula, DataTableFormula
    return text if isinstance(text, str) and text else None


def _value_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.10g}"
    return str(v)


def formulas_markdown(data: bytes, max_rows: int = MAX_FORMULA_ROWS) -> str:
    """Bảng công thức theo sheet: ô, công thức nguyên văn, giá trị Excel đã lưu.

    Giá trị lấy từ cache của file (data_only=True). File do thư viện sinh ra mà chưa
    mở bằng Excel thì không có cache, cột giá trị để trống.
    """
    try:
        from openpyxl import load_workbook
        from openpyxl.utils import get_column_letter

        wb_f = load_workbook(io.BytesIO(data), data_only=False, read_only=True)
        wb_v = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    except Exception:
        logger.warning("Không mở được xlsx để đọc công thức.", exc_info=True)
        return ""

    sections: list[str] = []
    total = 0
    truncated = False
    try:
        for ws_f, ws_v in zip(wb_f.worksheets, wb_v.worksheets, strict=False):
            # mỗi nhóm: [cột, dòng đầu, dòng cuối, pattern, công thức đầu, giá trị đầu]
            groups: list[list] = []
            open_by_col: dict[int, list] = {}
            for row_f, row_v in zip(ws_f.iter_rows(), ws_v.iter_rows(), strict=False):
                values = {getattr(c, "column", None): c.value for c in row_v}
                for cell in row_f:
                    text = _formula_text(cell.value)
                    col = getattr(cell, "column", None)
                    if text is None or col is None:
                        continue
                    pat = _pattern(text, cell.row)
                    g = open_by_col.get(col)
                    if g and g[3] == pat and g[2] == cell.row - 1:
                        g[2] = cell.row
                        continue
                    g = [col, cell.row, cell.row, pat, text, _value_text(values.get(col))]
                    groups.append(g)
                    open_by_col[col] = g
            if not groups:
                continue
            groups.sort(key=lambda g: (g[1], g[0]))
            lines = [
                f"### Sheet {ws_f.title}",
                "",
                "| Ô | Công thức | Giá trị |",
                "| --- | --- | --- |",
            ]
            for col, r1, r2, _pat, text, value in groups:
                if total >= max_rows:
                    truncated = True
                    break
                letter = get_column_letter(col)
                where = f"{letter}{r1}" if r1 == r2 else f"{letter}{r1}:{letter}{r2}"
                note = "" if r1 == r2 else f" (kéo xuống {r2 - r1 + 1} ô)"
                lines.append(f"| {where} | `{_cell(text)}`{note} | {_cell(value)} |")
                total += 1
            sections.append("\n".join(lines))
            if truncated:
                break
    except Exception:
        logger.warning("Lỗi khi đọc công thức xlsx; bỏ qua.", exc_info=True)
        return ""
    finally:
        wb_f.close()
        wb_v.close()
    if not sections:
        return ""
    out = "## Công thức trong file\n\n" + "\n\n".join(sections)
    if truncated:
        out += f"\n\n_(Chỉ liệt kê {max_rows} dòng công thức đầu tiên.)_"
    return out
