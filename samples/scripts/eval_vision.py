"""Chấm điểm một model Vision (API tương thích OpenAI) trên ảnh mẫu đã biết đáp án.

Chạy:
    uv run --with matplotlib python samples/scripts/eval_vision.py \
        --base-url https://generativelanguage.googleapis.com/v1beta/openai \
        --api-key "$GEMINI_API_KEY" --model gemini-3.5-flash-lite

Dùng đúng prompt mà pipeline dùng (ingest.vision.OpenAICompatVision).
"""

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from make_samples import COST, REVENUE, chart_png, logo_png, pie_png, scan_png, table_png  # noqa: E402

from ingest.vision import OpenAICompatVision  # noqa: E402

TABLE_ROWS = [
    ["NV001", "Nguyễn Văn An", "15.000.000", "2.000.000", "17.000.000"],
    ["NV002", "Trần Thị Bình", "12.500.000", "1.500.000", "14.000.000"],
    ["NV003", "Lê Hoàng Cường", "18.000.000", "2.500.000", "20.500.000"],
    ["NV004", "Phạm Thu Dung", "11.000.000", "1.000.000", "12.000.000"],
    ["Tổng cộng", "56.500.000", "7.000.000", "63.500.000"],
]
PIE = {"Miền Bắc": 38, "Miền Trung": 17, "Miền Nam": 35, "Xuất khẩu": 10}
SCAN_PHRASES = [
    "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM",
    "Điều 3. Giá trị hợp đồng và phương thức thanh toán",
    "450.000.000 đồng",
    "thuế giá trị gia tăng 10%",
    "đợt 2 thanh toán 70%",
    "0,05%",
]


def numbers(line: str) -> list[float]:
    found = re.findall(r"\d+(?:[.,]\d+)?", line.replace("~", ""))
    return [float(x.replace(",", ".")) for x in found]


def score_chart(md: str) -> tuple[int, int, list[str]]:
    """Doanh thu có nhãn nên phải đúng tuyệt đối; chi phí không có nhãn, cho sai 5%."""
    ok, notes = 0, []
    rows = {m: ln for ln in md.splitlines() for m in [f"T{i}" for i in range(1, 7)]
            if re.search(rf"\b{m}\b", ln)}  # fmt: skip
    for i, (rev, cost) in enumerate(zip(REVENUE, COST, strict=True), 1):
        nums = numbers(rows.get(f"T{i}", ""))
        if rev in nums:
            ok += 1
        else:
            notes.append(f"T{i} doanh thu {rev} không thấy (dòng: {rows.get(f'T{i}', '-')!r})")
        if any(abs(n - cost) <= cost * 0.05 for n in nums if n != rev):
            ok += 1
        else:
            notes.append(f"T{i} chi phí ~{cost} sai hoặc thiếu")
    return ok, 12, notes


def score_table(md: str) -> tuple[int, int, list[str]]:
    ok, total, notes = 0, 0, []
    lines = md.splitlines()
    for row in TABLE_ROWS:
        line = next((ln for ln in lines if row[0] in ln), "")
        for cell in row[1:]:
            total += 1
            if cell in line:
                ok += 1
            else:
                notes.append(f"{row[0]}: thiếu/sai {cell}")
    return ok, total, notes


def score_pie(md: str) -> tuple[int, int, list[str]]:
    ok, notes = 0, []
    for label, pct in PIE.items():
        line = next((ln for ln in md.splitlines() if label in ln), "")
        if pct in numbers(line):
            ok += 1
        else:
            notes.append(f"{label} {pct}% sai (dòng: {line!r})")
    return ok, len(PIE), notes


def score_scan(md: str) -> tuple[int, int, list[str]]:
    flat = " ".join(md.split())
    miss = [p for p in SCAN_PHRASES if p not in flat]
    return len(SCAN_PHRASES) - len(miss), len(SCAN_PHRASES), [f"thiếu: {p}" for p in miss]


def score_logo(md: str) -> tuple[int, int, list[str]]:
    if len(md.strip()) < 80:
        return 1, 1, []
    return 0, 1, [f"ảnh trang trí nhưng trả dài: {md[:80]!r}"]


CASES = [
    ("chart", chart_png, score_chart),
    ("pie", pie_png, score_pie),
    ("table", table_png, score_table),
    ("scan", scan_png, score_scan),
    ("logo", logo_png, score_logo),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--show", action="store_true", help="in nguyên câu trả lời")
    a = ap.parse_args()
    v = OpenAICompatVision(a.base_url, a.api_key, a.model, a.timeout)

    got = total = 0
    print(f"Model: {a.model}\n")
    for name, make, score in CASES:
        t0 = time.time()
        try:
            md = v.describe(make())
        except Exception as e:  # noqa: BLE001
            print(f"{name:6} LỖI: {e}")
            continue
        ok, n, notes = score(md)
        got, total = got + ok, total + n
        print(f"{name:6} {ok}/{n}  {time.time() - t0:5.1f}s")
        for note in notes[:6]:
            print(f"         - {note}")
        if a.show:
            print("  " + md.replace("\n", "\n  ") + "\n")
    print(f"\nTổng: {got}/{total} ({got / max(total, 1):.0%})")


if __name__ == "__main__":
    main()
