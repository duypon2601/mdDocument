# So sánh KashifAgha (rag-starter) và marketcalls (openrag) cho tài liệu tài chính

Cần chọn repo xử lý tốt hơn file Excel có nhúng ảnh và PDF tài chính (báo cáo có bảng số, biểu đồ, trang scan).

## Kết luận

Nên dùng KashifAgha (rag-starter). Repo này cắt ảnh và biểu đồ ra, nhờ vision model mô tả rồi lưu thành chunk riêng. openrag bỏ qua ảnh, nên biểu đồ trong báo cáo tài chính không vào được index.

openrag mạnh hơn ở citation và vận hành. Nếu cần các phần đó thì lấy openrag làm nền và tự thêm bước mô tả ảnh, cách làm ghi ở mục "Nếu chọn openrag làm nền".

## Bảng so sánh

| Tiêu chí | KashifAgha (rag-starter) | marketcalls (openrag) |
|---|---|---|
| Parser chính | Docling (gói tùy chọn), fallback pypdf | Docling (cài sẵn), pypdfium2 cho PDF nhiều chữ |
| OCR | RapidOCR, bật/tắt bằng `ocr_enabled` | RapidOCR, chế độ `auto` / `force` / `disabled`, có ngưỡng confidence |
| Bảng | `do_table_structure` + cell matching, xuất markdown | Docling TableItem, xuất markdown |
| Ảnh / biểu đồ | **Có**: `generate_picture_images=True`, vision model mô tả, chunk IMAGE | **Không**: `generate_picture_images=False`, bỏ qua PictureItem |
| Excel (.xlsx) | Qua Docling (bắt buộc cài extra) | Qua Docling, locator theo sheet |
| CSV | Chuyển thành bảng markdown | Tách đoạn, gắn kind `table` |
| Citation | Theo trang | Theo trang / sheet / slide, kèm tọa độ |
| Đánh dấu chất lượng OCR | `ocr_used`, `pages_without_text` | Danh sách trang OCR, trang OCR kém tin cậy |
| Vận hành | Django + Celery, gọn | Multi-tenant, RBAC, re-index theo revision, audit |

## Luồng xử lý ảnh

```
KashifAgha
  PDF/XLSX → Docling → TextItem  → chunk TEXT
                     → TableItem → chunk TABLE (markdown)
                     → PictureItem → PNG → vision model → chunk IMAGE (mô tả)

openrag
  PDF/XLSX → Docling → TextItem  → block text/heading
                     → TableItem → block table (markdown)
                     → PictureItem → (bỏ qua)
```

## Bằng chứng trong code

KashifAgha:
- `KashifAgha/rag-starter/backend/rag/extract.py:109-120`: bật table structure, picture images (`images_scale = 2.0`) và OCR.
- `KashifAgha/rag-starter/backend/rag/extract.py:145-189`: tách TableItem và PictureItem thành chunk riêng.
- `KashifAgha/rag-starter/backend/rag/image_captioner.py`: gọi vision model (OpenAI, Ollama, OpenRouter, vLLM…) để mô tả ảnh.
- `KashifAgha/rag-starter/backend/rag/conf.py:203-205`: mặc định `prefer_docling=True`, `ocr_enabled=True`.

openrag:
- `marketcalls/openrag/backend/src/openrag/modules/documents/pipeline.py:188-209`: `generate_page_images=False`, `generate_picture_images=False`.
- `marketcalls/openrag/backend/src/openrag/modules/documents/pipeline.py:433-438`: chỉ nhận TableItem và TextItem, các loại khác bị `continue`.
- `marketcalls/openrag/backend/src/openrag/modules/documents/pipeline.py:243-310`: tự quyết định có OCR trang hay không dựa trên diện tích ảnh bitmap.

## Lưu ý khi dùng KashifAgha

1. Cài Docling: `uv sync --extra docling`. Không cài thì PDF rơi về pypdf (chất lượng kém) và `.xlsx` gần như không đọc được.
2. Cấu hình vision model cho image captioner, nếu không thì chunk ảnh sẽ không có mô tả.
3. Docling kéo theo PyTorch nên image của ingestion worker khá nặng (repo đã cấu hình bản CPU).

## Nếu chọn openrag làm nền

Phần cần bổ sung:

1. Trong `build_pdf_pipeline_options`, bật `generate_picture_images=True`.
2. Trong vòng lặp `iterate_items()`, thêm nhánh `PictureItem`: lấy ảnh, gọi model có `supports_vision`, lưu mô tả thành block `kind="image"`.
3. Kiểm tra lại giới hạn `max_blocks` và `max_output_chars`, vì mô tả ảnh làm tăng số block.
