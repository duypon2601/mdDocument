"""Sinh bộ file mẫu (docx, pdf, xlsx) có ảnh, biểu đồ, công thức để thử bộ chuyển đổi.

Chạy lại được:  uv run --with matplotlib python samples/scripts/make_samples.py
"""

import io
import shutil
import subprocess
import tempfile
from pathlib import Path

import docx
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pymupdf  # noqa: E402
from docx.shared import Cm  # noqa: E402
from openpyxl import Workbook  # noqa: E402
from openpyxl.chart import BarChart, LineChart, PieChart, Reference  # noqa: E402
from openpyxl.drawing.image import Image as XlImage  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

OUT = Path(__file__).resolve().parents[1]
FONT = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
if not Path(FONT).exists():
    FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
plt.rcParams["font.family"] = "sans-serif"
matplotlib.font_manager.fontManager.addfont(FONT)
plt.rcParams["font.sans-serif"] = [matplotlib.font_manager.FontProperties(fname=FONT).get_name()]

MONTHS = [f"T{i}" for i in range(1, 7)]
REVENUE = [1250, 1380, 1520, 1475, 1690, 1820]  # triệu đồng
COST = [980, 1040, 1110, 1090, 1230, 1300]


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, size)


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def chart_png() -> bytes:
    fig, ax = plt.subplots(figsize=(8, 4.8), dpi=120)
    bars = ax.bar(MONTHS, REVENUE, color="#2f6db5", label="Doanh thu")
    ax.plot(MONTHS, COST, color="#d9822b", marker="o", linewidth=2, label="Chi phí")
    ax.bar_label(bars, fmt="%d", fontsize=11)
    ax.set_title("Doanh thu và chi phí 6 tháng đầu năm 2025", fontsize=15)
    ax.set_xlabel("Tháng", fontsize=12)
    ax.set_ylabel("Triệu đồng", fontsize=12)
    ax.legend(loc="upper left")
    ax.set_ylim(0, 2100)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def pie_png() -> bytes:
    fig, ax = plt.subplots(figsize=(6.5, 5), dpi=120)
    labels = ["Miền Bắc", "Miền Trung", "Miền Nam", "Xuất khẩu"]
    ax.pie([38, 17, 35, 10], labels=labels, autopct="%1.0f%%", textprops={"fontsize": 13})
    ax.set_title("Cơ cấu doanh thu theo khu vực năm 2025", fontsize=15)
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def table_png() -> bytes:
    """Ảnh giống ảnh chụp màn hình một bảng số trong phần mềm kế toán."""
    rows = [
        ["Mã NV", "Họ và tên", "Lương CB", "Phụ cấp", "Thực lĩnh"],
        ["NV001", "Nguyễn Văn An", "15.000.000", "2.000.000", "17.000.000"],
        ["NV002", "Trần Thị Bình", "12.500.000", "1.500.000", "14.000.000"],
        ["NV003", "Lê Hoàng Cường", "18.000.000", "2.500.000", "20.500.000"],
        ["NV004", "Phạm Thu Dung", "11.000.000", "1.000.000", "12.000.000"],
        ["", "Tổng cộng", "56.500.000", "7.000.000", "63.500.000"],
    ]
    widths = [130, 280, 190, 170, 190]
    rh, pad = 52, 12
    W, H = sum(widths) + 2, rh * len(rows) + 50
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 40], fill="#e9eef5")
    d.text((10, 6), "Bảng lương tháng 10/2025 - Phòng Kinh doanh", font=font(22), fill="black")
    y0 = 48
    for r, row in enumerate(rows):
        x = 1
        y = y0 + r * rh
        if r == 0:
            d.rectangle([1, y, W - 1, y + rh], fill="#c9d7ea")
        for c, cell in enumerate(row):
            d.rectangle([x, y, x + widths[c], y + rh], outline="#7a8799", width=1)
            f = font(22) if r else ImageFont.truetype(FONT, 22)
            d.text((x + pad, y + 13), cell, font=f, fill="black")
            x += widths[c]
    return png_bytes(img)


SCAN_TEXT = [
    "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM",
    "Độc lập - Tự do - Hạnh phúc",
    "",
    "Điều 3. Giá trị hợp đồng và phương thức thanh toán",
    "3.1. Tổng giá trị hợp đồng là 450.000.000 đồng (Bốn trăm năm mươi",
    "triệu đồng), đã bao gồm thuế giá trị gia tăng 10%.",
    "3.2. Bên A thanh toán cho Bên B làm hai đợt bằng chuyển khoản:",
    "đợt 1 tạm ứng 30% trong vòng 07 ngày kể từ ngày ký hợp đồng;",
    "đợt 2 thanh toán 70% còn lại sau khi hai bên ký biên bản nghiệm thu.",
    "3.3. Nếu chậm thanh toán, Bên A chịu lãi suất 0,05% mỗi ngày trên",
    "số tiền chậm trả, nhưng không quá 8% giá trị phần nghĩa vụ vi phạm.",
]


def scan_png(lines=SCAN_TEXT, size: int = 30, w: int = 1400) -> bytes:
    """Đoạn văn tiếng Việt in ra ảnh, hơi xám và nghiêng nhẹ như bản scan."""
    lh = int(size * 1.6)
    img = Image.new("L", (w, lh * len(lines) + 80), 244)
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        bold = i < 2
        f = font(size + (2 if bold else 0))
        x = (w - d.textlength(line, font=f)) / 2 if bold else 60
        d.text((x, 40 + i * lh), line, font=f, fill=25)
    img = img.rotate(0.6, expand=False, fillcolor=244, resample=Image.BICUBIC)
    return png_bytes(img.convert("RGB"))


def logo_png() -> bytes:
    img = Image.new("RGB", (48, 48), "white")
    d = ImageDraw.Draw(img)
    d.ellipse([4, 4, 44, 44], fill="#c0392b")
    d.text((14, 12), "VN", font=font(18), fill="white")
    data = png_bytes(img)
    assert len(data) < 2048, len(data)
    return data


# ---------------------------------------------------------------- DOCX
def make_docx(chart: bytes, table: bytes, scan: bytes, logo: bytes) -> None:
    d = docx.Document()
    d.add_picture(io.BytesIO(logo), width=Cm(1.2))
    d.add_heading("Báo cáo kết quả kinh doanh 6 tháng đầu năm 2025", 1)
    d.add_paragraph(
        "Kính gửi Ban Giám đốc Công ty Cổ phần Thương mại Minh Phát. Phòng Kế toán xin báo cáo "
        "kết quả kinh doanh từ tháng 1 đến tháng 6 năm 2025 như sau."
    )
    d.add_heading("1. Doanh thu và chi phí", 2)
    d.add_paragraph(
        "Doanh thu tăng đều qua các tháng, riêng tháng 4 giảm nhẹ do nghỉ lễ. Tổng doanh thu "
        "6 tháng đạt 9.135 triệu đồng, chi phí 6.750 triệu đồng."
    )
    d.add_picture(io.BytesIO(chart), width=Cm(15))
    d.add_paragraph("Hình 1. Biểu đồ doanh thu và chi phí theo tháng.")
    d.add_heading("2. Quỹ lương", 2)
    d.add_paragraph("Bảng lương phòng Kinh doanh tháng 10 được chụp từ phần mềm MISA:")
    d.add_picture(io.BytesIO(table), width=Cm(16))
    d.add_paragraph("Quỹ lương phòng Kinh doanh tháng 10 là 63,5 triệu đồng.")
    d.add_heading("3. Hợp đồng lớn trong kỳ", 2)
    d.add_paragraph("Trích Điều 3 hợp đồng số 12/2025/HĐMB với Công ty TNHH Hòa Bình (bản scan):")
    d.add_picture(io.BytesIO(scan), width=Cm(16))
    d.add_paragraph("Phòng Kế toán đề nghị theo dõi tiến độ thanh toán đợt 2.")
    d.add_paragraph("Người lập báo cáo: Trần Thị Mai")
    d.save(OUT / "bao-cao-co-anh.docx")


# ---------------------------------------------------------------- PDF
def make_pdf(chart: bytes, scan: bytes) -> None:
    doc = pymupdf.open()
    fontfile = FONT
    W, H = pymupdf.paper_size("a4")

    def text_page(title: str, body: list[str]) -> None:
        p = doc.new_page(width=W, height=H)
        p.insert_font(fontname="vn", fontfile=fontfile)
        p.insert_text((60, 80), title, fontname="vn", fontsize=16)
        y = 120
        for line in body:
            p.insert_text((60, y), line, fontname="vn", fontsize=11.5)
            y += 20

    # Trang 1: text thật
    text_page(
        "HỢP ĐỒNG MUA BÁN HÀNG HÓA Số: 12/2025/HĐMB",
        [
            "Hôm nay, ngày 15 tháng 3 năm 2025, tại Hà Nội, chúng tôi gồm:",
            "BÊN A (Bên mua): CÔNG TY TNHH HÒA BÌNH",
            "Địa chỉ: Số 25 Lê Duẩn, phường Cửa Nam, quận Hoàn Kiếm, Hà Nội",
            "Mã số thuế: 0101234567. Đại diện: Ông Nguyễn Văn Hùng, Giám đốc",
            "BÊN B (Bên bán): CÔNG TY CỔ PHẦN THƯƠNG MẠI MINH PHÁT",
            "Địa chỉ: Số 88 Nguyễn Trãi, phường Thượng Đình, quận Thanh Xuân, Hà Nội",
            "Mã số thuế: 0109876543. Đại diện: Bà Lê Thu Hà, Tổng Giám đốc",
            "",
            "Điều 1. Hàng hóa",
            "Bên B bán cho Bên A 300 bộ máy tính để bàn Dell OptiPlex 7010,",
            "đơn giá 15.000.000 đồng/bộ (chưa gồm VAT), hàng mới 100%.",
            "Điều 2. Thời gian và địa điểm giao hàng",
            "Bên B giao hàng trong vòng 30 ngày kể từ ngày ký, tại kho của Bên A.",
        ],
    )
    # Trang 2: chỉ ảnh (bản scan Điều 3), không có lớp text
    p = doc.new_page(width=W, height=H)
    p.insert_image(pymupdf.Rect(40, 60, W - 40, 60 + (W - 80) * 0.45), stream=scan)
    # Trang 3: text thật
    text_page(
        "Điều 4. Bảo hành",
        [
            "Bên B bảo hành sản phẩm 36 tháng kể từ ngày nghiệm thu.",
            "Trong thời gian bảo hành, Bên B sửa chữa hoặc thay thế miễn phí",
            "các lỗi do nhà sản xuất trong vòng 48 giờ kể từ khi nhận thông báo.",
            "Điều 5. Điều khoản chung",
            "Hợp đồng lập thành 04 bản có giá trị pháp lý như nhau, mỗi bên giữ 02 bản.",
            "Hợp đồng có hiệu lực kể từ ngày ký.",
        ],
    )
    # Trang 4: chỉ ảnh, trang chữ ký và con dấu scan
    sig = scan_png(
        [
            "ĐẠI DIỆN BÊN A                         ĐẠI DIỆN BÊN B",
            "(Ký, ghi rõ họ tên, đóng dấu)        (Ký, ghi rõ họ tên, đóng dấu)",
            "",
            "",
            "Nguyễn Văn Hùng                          Lê Thu Hà",
        ],
        size=32,
    )
    p = doc.new_page(width=W, height=H)
    p.insert_image(pymupdf.Rect(40, 80, W - 40, 80 + (W - 80) * 0.3), stream=sig)
    # Trang 5: phụ lục có một dòng text và một ảnh biểu đồ
    p = doc.new_page(width=W, height=H)
    p.insert_font(fontname="vn", fontfile=fontfile)
    p.insert_text((60, 70), "Phụ lục 1. Tiến độ giao hàng dự kiến", fontname="vn", fontsize=14)
    p.insert_image(pymupdf.Rect(50, 90, W - 50, 90 + (W - 100) * 0.6), stream=chart)
    # Trang 6: chỉ ảnh biểu đồ (không có chữ nào ở lớp text)
    p = doc.new_page(width=W, height=H)
    p.insert_image(pymupdf.Rect(50, 60, W - 50, 60 + (W - 100) * 0.77), stream=pie_png())
    doc.subset_fonts()  # Arial Unicode nhúng nguyên font thì file ~15MB
    doc.save(OUT / "hop-dong-scan.pdf", deflate=True, garbage=3)


# ---------------------------------------------------------------- XLSX
def make_xlsx(chart: bytes, table: bytes, scan: bytes) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Doanh thu"
    ws["A1"] = "Thuế suất VAT"
    ws["B1"] = 0.1
    ws.append([])
    ws.append(["Mã SP", "Đơn giá", "Số lượng", "Thành tiền", "VAT", "Xếp loại", "Tên SP"])
    products = ["SP01", "SP02", "SP03", "SP04", "SP05"]
    for r in range(4, 52):  # 48 dòng dữ liệu, công thức kéo xuống
        ws.cell(r, 1, products[(r - 4) % 5])
        ws.cell(r, 2, 100_000 + ((r * 37) % 9) * 25_000)
        ws.cell(r, 3, 5 + (r * 7) % 40)
        ws.cell(r, 4, f"=B{r}*C{r}")
        ws.cell(r, 5, f"=D{r}*$B$1")
        ws.cell(r, 6, f'=IF(D{r}>=3000000,"Cao","Thấp")')
        ws.cell(r, 7, f"=VLOOKUP(A{r},'Danh mục'!$A$2:$C$6,2,FALSE)")
    ws["C53"] = "Tổng"
    ws["D53"] = "=SUM(D4:D51)"
    ws["E53"] = "=SUM(E4:E51)"
    ws["C54"] = "Trung bình"
    ws["D54"] = "=AVERAGE(D4:D51)"
    ws["C55"] = "Chiết khấu"
    ws["D55"] = "='Danh mục'!E2*D53"
    ws["C56"] = "Giá SP03"
    ws["D56"] = '=_xlfn.XLOOKUP("SP03",\'Danh mục\'!A2:A6,\'Danh mục\'!C2:C6)'

    # Bảng tổng hợp theo tháng cho chart
    ws["I3"], ws["J3"], ws["K3"] = "Tháng", "Doanh thu", "Chi phí"
    for i, (m, rv, c) in enumerate(zip(MONTHS, REVENUE, COST), start=4):
        ws.cell(i, 9, m)
        ws.cell(i, 10, rv)
        ws.cell(i, 11, c)
    bar = BarChart()
    bar.title = "Doanh thu và chi phí 6 tháng đầu năm"
    bar.x_axis.title = "Tháng"
    bar.y_axis.title = "Triệu đồng"
    bar.add_data(Reference(ws, min_col=10, max_col=10, min_row=3, max_row=9), titles_from_data=True)
    bar.set_categories(Reference(ws, min_col=9, min_row=4, max_row=9))
    line = LineChart()
    line.add_data(Reference(ws, min_col=11, min_row=3, max_row=9), titles_from_data=True)
    bar += line
    ws.add_chart(bar, "I12")

    ws["I30"], ws["J30"] = "Khu vực", "Tỷ trọng"
    for i, (k, v) in enumerate(
        [("Miền Bắc", 38), ("Miền Trung", 17), ("Miền Nam", 35), ("Xuất khẩu", 10)], start=31
    ):
        ws.cell(i, 9, k)
        ws.cell(i, 10, v)
    pie = PieChart()
    pie.title = "Cơ cấu doanh thu theo khu vực"
    pie.add_data(Reference(ws, min_col=10, min_row=30, max_row=34), titles_from_data=True)
    pie.set_categories(Reference(ws, min_col=9, min_row=31, max_row=34))
    ws.add_chart(pie, "I36")

    cat = wb.create_sheet("Danh mục")
    cat.append(["Mã SP", "Tên SP", "Giá niêm yết", "", "Chiết khấu"])
    for row in [
        ["SP01", "Máy tính Dell OptiPlex", 15_000_000],
        ["SP02", "Màn hình LG 24 inch", 3_200_000],
        ["SP03", "Bàn phím Logitech", 450_000],
        ["SP04", "Chuột không dây", 250_000],
        ["SP05", "Máy in Canon LBP", 4_800_000],
    ]:
        cat.append(row)
    cat["E2"] = 0.03

    img_ws = wb.create_sheet("Ảnh chụp")
    img_ws["A1"] = "Phụ lục: ảnh chụp chứng từ"
    for png, anchor in [(chart, "A3"), (table, "A30"), (scan, "A52")]:
        x = XlImage(io.BytesIO(png))
        x.width, x.height = x.width * 0.7, x.height * 0.7
        img_ws.add_image(x, anchor)

    path = OUT / "bao-cao-tai-chinh.xlsx"
    wb.save(path)
    return path


def libreoffice_resave(path: Path) -> None:
    soffice = shutil.which("soffice") or (
        "/Applications/LibreOffice.app/Contents/MacOS/soffice"
        if Path("/Applications/LibreOffice.app").exists()
        else None
    )
    if not soffice:
        print("LibreOffice (soffice) chưa cài: bỏ qua bản có cache giá trị.")
        return
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "xlsx", "--outdir", tmp, str(path)],
            check=True,
        )
        shutil.move(Path(tmp) / path.name, OUT / f"{path.stem}-libreoffice.xlsx")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    chart, table, scan, logo = chart_png(), table_png(), scan_png(), logo_png()
    for name, data in [("chart", chart), ("table", table), ("scan", scan), ("logo", logo)]:
        (OUT / "images").mkdir(exist_ok=True)
        (OUT / "images" / f"{name}.png").write_bytes(data)
    make_docx(chart, table, scan, logo)
    make_pdf(chart, scan)
    libreoffice_resave(make_xlsx(chart, table, scan))
    for p in sorted(OUT.glob("*.*")):
        print(f"{p.name:40s} {p.stat().st_size:>9,d} B")


if __name__ == "__main__":
    main()
