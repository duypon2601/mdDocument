"""Conversion Worker (convert-tq): detect_format, parse_document, ocr_pages, finalize_markdown."""

import asyncio
import logging
import time

from temporalio import activity
from temporalio.exceptions import ApplicationError

from ingest.convert.ocr import OcrEngine
from ingest.convert.parsers import (
    docx_charts,
    docx_images,
    image_kind,
    pptx_media,
    vn_syllable,
    xlsx_media,
    xlsx_tables,
)
from ingest.convert.parsers import pdf as pdf_parser
from ingest.convert.parsers.detect import sniff
from ingest.convert.parsers.extract import extract_bytes
from ingest.convert.parsers.merge import merge_markdown, page_marker
from ingest.convert.vision import VisionEngine, shrink_for_vision
from ingest.core import keys
from ingest.core.errors import EMPTY_DOCUMENT, IngestError, to_application_error
from ingest.core.models import (
    FinalizeInput,
    FinalizeResult,
    FormatInfo,
    IngestInput,
    OcrBatch,
    OcrResult,
    PartResult,
)
from ingest.core.storage import Storage

logger = logging.getLogger(__name__)

HEARTBEAT_EVERY = 20.0

# v2: OCR có dấu nhưng sai âm tiết (vd. "vién") từ ngưỡng này thì gửi VLM đọc lại.
# Đo trên 79 trang BCTC scan: trung vị 0,4%; ngưỡng 1% chọn ra 10 trang lỗi nặng nhất.
BAD_DIACRITIC_RATIO = 0.01
MIN_DIACRITIC_WORDS = 30
VISION_RETRY_DELAYS = (2.0, 5.0, 10.0)  # v2: gọi lại khi 429/503


def chunked(items: list[int], n: int) -> list[list[int]]:
    return [items[i : i + n] for i in range(0, len(items), n)]


def vision_reason(
    text: str,
    confidence: float,
    min_confidence: float,
    png: bytes | None = None,
    version: int = 2,
) -> str | None:
    """Lý do chuyển ảnh sang Vision LLM; None là giữ kết quả OCR."""
    if confidence < min_confidence:
        return f"OCR tin cậy thấp {confidence:.2f}"
    reason = image_kind.graphic_reason(text, png)
    if reason or version < 2:
        return reason
    bad, words = vn_syllable.bad_diacritic_ratio(text)
    if words >= MIN_DIACRITIC_WORDS and bad >= BAD_DIACRITIC_RATIO:
        return f"sai dấu {bad:.1%}"
    return None


def needs_vision(
    text: str, confidence: float, min_confidence: float, png: bytes | None = None
) -> bool:
    """Chart, sơ đồ, bảng chụp hoặc OCR kém thì chuyển Vision LLM (luật v1)."""
    return vision_reason(text, confidence, min_confidence, png, version=1) is not None


def _status_code(exc: Exception) -> int | None:
    resp = getattr(exc, "response", None)
    return getattr(resp, "status_code", None)


async def run_with_heartbeat(fn, *args):
    """Chạy hàm chặn trong thread, heartbeat đều vì một lần gọi Vision LLM có thể quá 1 phút."""
    task = asyncio.ensure_future(asyncio.to_thread(fn, *args))
    while True:
        done, _ = await asyncio.wait({task}, timeout=HEARTBEAT_EVERY)
        if done:
            return task.result()
        activity.heartbeat()


def place_docx_images(parts: list[str]) -> list[str]:
    """Phần đầu là text, sau là OCR. Nội dung ảnh (docx, pptx, hình trong PDF) được chèn
    vào chỗ marker trong text."""
    if not parts:
        return parts
    images: dict[str, str] = {}
    rest: list[str] = []
    for part in parts[1:]:
        remain, found = docx_images.split_image_blocks(part)
        images.update(found)
        rest.append(remain)
    return [docx_images.place_images(parts[0], images), *rest]


class ConvertActivities:
    def __init__(
        self,
        storage: Storage,
        ocr: OcrEngine,
        pages_per_batch: int = 10,
        prefer_docling: bool = False,
        vision: VisionEngine | None = None,
        docx_image_mode: str = "auto",
        docx_min_image_bytes: int = 2048,
        min_ocr_confidence: float = 0.6,
        xlsx_formulas: bool = True,
    ) -> None:
        self.xlsx_formulas = xlsx_formulas
        self.vision_retry_delays = VISION_RETRY_DELAYS
        self.prefer_docling = prefer_docling
        self.vision = vision
        self.docx_image_mode = docx_image_mode
        self.docx_min_image_bytes = docx_min_image_bytes
        self.min_ocr_confidence = min_ocr_confidence
        self.storage = storage
        self.ocr = ocr
        self.pages_per_batch = pages_per_batch

    async def _read(self, key: str) -> bytes:
        return await asyncio.to_thread(self.storage.get, key)

    @activity.defn(name="detect_format")
    async def detect_format(self, inp: IngestInput) -> FormatInfo:
        data = await self._read(inp.raw_key)
        try:
            kind, mime = sniff(data, inp.file_name)
            if kind == "pdf":
                doc = pdf_parser.open_pdf(data)
                text_pages, ocr_pages = await asyncio.to_thread(pdf_parser.classify_pages, doc)
                items = list(ocr_pages)
                if inp.extract_media:  # ảnh trên trang có chữ: số >= page_count
                    figures = await asyncio.to_thread(pdf_parser.list_figures, doc, text_pages)
                    items += [doc.page_count + k for k in range(len(figures))]
                return FormatInfo(
                    doc_id=inp.doc_id, kind=kind, mime=mime, page_count=doc.page_count,
                    has_text=bool(text_pages),
                    ocr_page_batches=chunked(items, self.pages_per_batch),
                )  # fmt: skip
            if kind == "image":
                return FormatInfo(
                    doc_id=inp.doc_id, kind=kind, mime=mime, page_count=1, has_text=False,
                    ocr_page_batches=[[0]],
                )  # fmt: skip
            if kind in ("docx", "pptx") and inp.extract_media:
                slots = await asyncio.to_thread(self._ocr_slots, data, kind)
                return FormatInfo(
                    doc_id=inp.doc_id, kind=kind, mime=mime, has_text=True,
                    ocr_page_batches=chunked(slots, self.pages_per_batch),
                )  # fmt: skip
            if kind == "xlsx" and inp.extract_media:  # ảnh đi OCR; chart đọc ở parse_document
                images = await asyncio.to_thread(
                    xlsx_media.list_images, data, self.docx_min_image_bytes
                )
                return FormatInfo(
                    doc_id=inp.doc_id, kind=kind, mime=mime, has_text=True,
                    ocr_page_batches=chunked(list(range(len(images))), self.pages_per_batch),
                )  # fmt: skip
            return FormatInfo(doc_id=inp.doc_id, kind=kind, mime=mime, has_text=True)
        except IngestError as e:
            raise to_application_error(e) from e

    @activity.defn(name="parse_document")
    async def parse_document(self, inp: IngestInput) -> PartResult:
        data = await self._read(inp.raw_key)
        try:
            kind, _ = sniff(data, inp.file_name)
            out_key = keys.md_raw_text_key(inp.doc_id)
            page_count = 0
            if kind == "pdf":
                doc = pdf_parser.open_pdf(data)
                page_count = doc.page_count
                text_pages, _ocr = await asyncio.to_thread(pdf_parser.classify_pages, doc)
                by_page: dict[int, list] = {}
                if inp.extract_media:
                    figures = await asyncio.to_thread(pdf_parser.list_figures, doc, text_pages)
                    for k, (page, rect) in enumerate(figures):
                        by_page.setdefault(page, []).append((pdf_parser.figure_name(k), rect))
                parts = []
                for i in text_pages:
                    activity.heartbeat({"page": i})
                    if inp.extract_media:
                        md = await asyncio.to_thread(
                            pdf_parser.page_markdown_with_figures, doc, i, by_page.get(i, [])
                        )
                    else:  # bản cũ: giữ nguyên output pymupdf4llm
                        md = await asyncio.to_thread(pdf_parser.page_markdown, doc, i)
                    parts.append(f"{page_marker(i + 1)}\n\n{md}")
                md = "\n\n".join(parts)
            elif kind == "image":
                md = ""  # ảnh chỉ đi đường OCR
            elif inp.extract_media and kind in ("docx", "pptx", "xlsx"):
                md = await asyncio.to_thread(self._office_markdown, data, inp.file_name, kind)
                md = await self._add_media_parts(md, data, kind)
            else:  # html, text, bản cũ: Docling -> MarkItDown -> parser riêng
                md = await asyncio.to_thread(
                    extract_bytes, data, inp.file_name, kind, self.prefer_docling
                )
        except IngestError as e:
            raise to_application_error(e) from e
        await asyncio.to_thread(self.storage.put, out_key, md.encode())
        return PartResult(doc_id=inp.doc_id, md_key=out_key, page_count=page_count)

    def _office_markdown(self, data: bytes, file_name: str, kind: str) -> str:
        """Office khi bóc media: parser riêng trước, lỗi hoặc rỗng thì quay về MarkItDown."""
        if kind == "pptx":  # ảnh thành marker để OCR, chart thành bảng
            try:
                md = pptx_media.to_markdown(data)
                if md.strip():
                    return md
            except Exception:
                logger.warning("python-pptx không đọc được file; dùng MarkItDown.", exc_info=True)
        if kind == "xlsx":  # bảng tách theo vùng ô, không NaN/Unnamed
            md = xlsx_tables.workbook_markdown(data)
            if md.strip():
                return md
        if kind == "docx":  # chart gốc thành token để giữ vị trí qua mammoth
            tokenized, charts = docx_charts.tokenize_charts(data)
            md = extract_bytes(tokenized, file_name, kind, self.prefer_docling)
            return docx_charts.fill_tokens(md, charts) if charts else md
        return extract_bytes(data, file_name, kind, self.prefer_docling)

    async def _add_media_parts(self, md: str, data: bytes, kind: str) -> str:
        if kind == "docx":  # placeholder ảnh -> marker để finalize chèn nội dung ảnh
            slots = await asyncio.to_thread(docx_images.image_slots, data)
            return docx_images.mark_placeholders(md, slots)
        if kind == "xlsx":  # MarkItDown bỏ qua chart, đọc thẳng từ XML của chart
            extra = [await asyncio.to_thread(xlsx_media.charts_markdown, data)]
            if self.xlsx_formulas:
                extra.append(await asyncio.to_thread(xlsx_media.formulas_markdown, data))
            return "\n\n".join([md, *[e for e in extra if e]]).strip()
        return md

    def _ocr_slots(self, data: bytes, kind: str) -> list[int]:
        if kind == "pptx":
            try:
                return pptx_media.readable_slot_indices(data, self.docx_min_image_bytes)
            except Exception:  # parse_document cũng sẽ lùi về MarkItDown
                logger.warning("Không liệt kê được ảnh pptx; bỏ qua ảnh.", exc_info=True)
                return []
        if not docx_images.has_media(data):  # fast-path: không có ảnh
            return []
        return docx_images.readable_slot_indices(data, self.docx_min_image_bytes)

    @activity.defn(name="ocr_pages")
    async def ocr_pages(self, batch: OcrBatch) -> OcrResult:
        data = await self._read(batch.raw_key)
        if batch.kind == "docx":
            return await self._ocr_slot_images(batch, data, docx_images.image_slots)
        if batch.kind == "pptx":
            return await self._ocr_slot_images(batch, data, pptx_media.image_slots)
        if batch.kind == "xlsx":
            return await self._ocr_xlsx_images(batch, data)
        try:
            doc = pdf_parser.open_pdf(data) if batch.kind == "pdf" else None
        except IngestError as e:
            raise to_application_error(e) from e
        texts: list[str] = []
        confs: list[float] = []
        figures = None
        for page in batch.pages:
            activity.heartbeat({"page": page})  # cũng là điểm nhận lệnh huỷ
            if doc is not None and page >= doc.page_count:  # hình trên trang có chữ
                if figures is None:
                    text_pages, _ = await asyncio.to_thread(pdf_parser.classify_pages, doc)
                    figures = await asyncio.to_thread(pdf_parser.list_figures, doc, text_pages)
                k = page - doc.page_count
                if k >= len(figures):
                    continue
                png = await asyncio.to_thread(pdf_parser.render_figure_png, doc, *figures[k])
                where = f"{batch.doc_id[:12]} hình {k + 1} (trang {figures[k][0] + 1})"
                text, conf = await self._read_image(png, batch.pipeline_version, where)
                marker = docx_images.image_marker(pdf_parser.figure_name(k))
                texts.append(f"{marker}\n\n{text.strip()}")
                confs.append(conf)
                continue
            png = (
                await asyncio.to_thread(pdf_parser.render_page_png, doc, page)
                if doc is not None
                else data
            )
            where = f"{batch.doc_id[:12]} trang {page + 1}"
            text, conf = await self._read_image(png, batch.pipeline_version, where)
            texts.append(f"{page_marker(page + 1)}\n\n{text.strip()}")
            confs.append(conf)
        key = keys.md_raw_ocr_key(batch.doc_id, batch.batch_index)
        await asyncio.to_thread(self.storage.put, key, "\n\n".join(texts).encode())
        confidence = sum(confs) / len(confs) if confs else 1.0
        return OcrResult(batch.doc_id, batch.batch_index, key, confidence)

    async def _ocr_slot_images(self, batch: OcrBatch, data: bytes, slots_fn) -> OcrResult:
        """pages là chỉ số slot ảnh (docx_images/pptx_media.image_slots), không phải số trang."""
        slots = await asyncio.to_thread(slots_fn, data)
        blocks: list[str] = []
        confs: list[float] = []
        for idx in batch.pages:
            activity.heartbeat({"image": idx})
            if idx >= len(slots):
                continue
            name = slots[idx]
            try:
                png = await asyncio.to_thread(docx_images.read_png, data, name)
            except Exception:
                logger.warning("Bỏ qua ảnh hỏng %s trong %s", name, batch.doc_id, exc_info=True)
                continue
            if png is None:
                continue
            where = f"{batch.doc_id[:12]} {name}"
            text, conf = await self._read_image(png, batch.pipeline_version, where)
            blocks.append(f"{docx_images.image_marker(name)}\n\n{text.strip()}")
            confs.append(conf)
        key = keys.md_raw_ocr_key(batch.doc_id, batch.batch_index)
        await asyncio.to_thread(self.storage.put, key, "\n\n".join(blocks).encode())
        confidence = sum(confs) / len(confs) if confs else 1.0
        return OcrResult(batch.doc_id, batch.batch_index, key, confidence)

    async def _ocr_xlsx_images(self, batch: OcrBatch, data: bytes) -> OcrResult:
        """pages là chỉ số ảnh trong xlsx_media.list_images, không phải số trang."""
        images = await asyncio.to_thread(xlsx_media.list_images, data, self.docx_min_image_bytes)
        blocks: list[str] = []
        confs: list[float] = []
        for idx in batch.pages:
            activity.heartbeat({"image": idx})
            if idx >= len(images):
                continue
            img = images[idx]
            try:
                png = await asyncio.to_thread(docx_images.read_png, data, img.path)
            except Exception:
                logger.warning("Bỏ qua ảnh hỏng %s trong %s", img.path, batch.doc_id, exc_info=True)
                continue
            if png is None:
                continue
            where = f"{batch.doc_id[:12]} {img.path}"
            text, conf = await self._read_image(png, batch.pipeline_version, where)
            confs.append(conf)
            if text.strip():
                where = img.label()
                head = f"### Ảnh {idx + 1}" + (f" ({where})" if where else "")
                blocks.append(f"{head}\n\n{text.strip()}")
        key = keys.md_raw_ocr_key(batch.doc_id, batch.batch_index)
        await asyncio.to_thread(self.storage.put, key, "\n\n".join(blocks).encode())
        confidence = sum(confs) / len(confs) if confs else 1.0
        return OcrResult(batch.doc_id, batch.batch_index, key, confidence)

    async def _try_vision(
        self, png: bytes, version: int = 2, where: str = "", reason: str = ""
    ) -> str | None:
        """Gọi Vision LLM, ghi log mỗi lần gọi. v2: thu nhỏ ảnh, gọi lại khi 429/503."""
        if self.vision is None:
            return None
        image = await asyncio.to_thread(shrink_for_vision, png) if version >= 2 else png
        delays = self.vision_retry_delays if version >= 2 else ()
        for attempt in range(len(delays) + 1):
            t0 = time.monotonic()
            try:
                text = await run_with_heartbeat(self.vision.describe, image)
            except Exception as e:
                code = _status_code(e)
                logger.warning(
                    "VLM lỗi | %s | v%d | %s | %s | lần %d | %.1fs",
                    where, version, reason, code or type(e).__name__, attempt + 1,
                    time.monotonic() - t0,
                )  # fmt: skip
                if code in (429, 503) and attempt < len(delays):
                    await self._sleep_with_heartbeat(delays[attempt])
                    continue
                logger.warning("VLM bỏ cuộc, giữ kết quả OCR | %s", where, exc_info=True)
                return None
            logger.info(
                "VLM ok | %s | v%d | %s | %d KB | %.1fs | %d ký tự",
                where, version, reason, len(image) // 1024, time.monotonic() - t0, len(text),
            )  # fmt: skip
            return text
        return None

    async def _sleep_with_heartbeat(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            activity.heartbeat()
            await asyncio.sleep(min(left, HEARTBEAT_EVERY))

    async def _read_image(self, png: bytes, version: int = 2, where: str = "") -> tuple[str, float]:
        """Trả (markdown, độ tin cậy). Kết quả Vision LLM tính độ tin cậy 1.0."""
        mode = self.docx_image_mode if self.vision is not None else "ocr"
        if mode == "vision":
            text = await self._try_vision(png, version, where, "chế độ vision")
            if text is not None:
                return text, 1.0
        try:
            text, conf = await run_with_heartbeat(self.ocr.recognize, png)
        except ApplicationError as e:
            if e.type != "OCR_UNAVAILABLE" or mode == "ocr":
                raise
            v = await self._try_vision(png, version, where, "không có OCR")
            if v is None:
                raise
            return v, 1.0
        reason = None
        if mode == "auto":
            reason = await asyncio.to_thread(
                vision_reason, text, conf, self.min_ocr_confidence, png, version
            )
        if reason:
            v = await self._try_vision(png, version, where, reason)
            if v:  # Vision trả rỗng (ảnh trang trí) thì giữ chữ OCR đọc được
                return v, 1.0
        else:
            logger.info("OCR | %s | v%d | tin cậy %.2f | %d ký tự", where, version, conf, len(text))
        return text, conf

    @activity.defn(name="finalize_markdown")
    async def finalize_markdown(self, inp: FinalizeInput) -> FinalizeResult:
        def work() -> FinalizeResult:
            part_keys = [keys.md_raw_text_key(inp.doc_id)] + [
                keys.md_raw_ocr_key(inp.doc_id, b) for b in sorted(inp.ocr_batches)
            ]
            parts = [self.storage.get(k).decode() for k in part_keys if self.storage.exists(k)]
            parts = place_docx_images(parts)
            md, chars = merge_markdown(parts, inp.file_name, inp.doc_id, inp.page_count)
            if chars == 0:
                raise ApplicationError(
                    "Tài liệu không có nội dung", type=EMPTY_DOCUMENT, non_retryable=True
                )
            key = keys.md_key(inp.doc_id)
            self.storage.put(key, md.encode())
            return FinalizeResult(inp.doc_id, key, chars)

        return await asyncio.to_thread(work)
