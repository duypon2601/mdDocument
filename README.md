# Document Ingestion System

Hệ thống nạp tài liệu (PDF, Office, HTML) chạy trên Temporal: chuyển sang Markdown, OCR khi cần, chia chunk, embedding rồi ghi vào Qdrant. Kiến trúc và các bước xử lý nằm trong [docs/c4-model.md](docs/c4-model.md).

## Cấu trúc code

Mỗi container ở Level 2 trong [docs/c4-model.md](docs/c4-model.md) là một package riêng trong uv workspace:

| Package | Thư mục | Container |
|---|---|---|
| `ingest-core` | `packages/core` | Phần dùng chung: config, payload Temporal, key storage, Metadata DB, định dạng Markdown trung gian |
| `ingest-api` | `packages/api` | Ingestion API |
| `ingest-convert` | `packages/convert` | Conversion Worker |
| `ingest-index` | `packages/index` | Indexing Worker (workflow + chunk, embed, upsert) |
| `ingest-cli` | `packages/cli` | CLI `ingest`, gọi API qua HTTP |

Ba package `api`, `convert` và `index` chỉ phụ thuộc `core`, không import lẫn nhau. Workflow gọi activity convert theo tên qua Temporal. `tests/test_package_boundaries.py` kiểm tra ranh giới này. Mỗi package có dependency riêng, nên cài một package không kéo theo thư viện của package khác (ví dụ `uv sync --package ingest-api`).

## Yêu cầu

- Docker và Docker Compose
- [uv](https://docs.astral.sh/uv/) với Python 3.12
- libmagic (macOS: `brew install libmagic`; Debian/Ubuntu: `apt install libmagic1`)
- Một endpoint embedding tương thích OpenAI. Mặc định là Ollama với model `bge-m3` tại `localhost:11434`.

## Chạy thử

```bash
cp .env.example .env
docker compose up -d      # postgres, temporal 1.32.2, temporal-ui, minio, qdrant
uv sync
```

Temporal UI ở http://localhost:8080, MinIO console ở http://localhost:9001.

Mở ba terminal:

```bash
uv run ingest worker convert
uv run ingest worker index   # chạy cả workflow (ingest-tq) lẫn index (index-tq)
uv run ingest api              # http://localhost:8000
```

Muốn chạy cả ba trong Docker thì dùng `docker compose --profile app up -d --build`. Dockerfile có ba target `api`, `convert`, `index`. Mỗi image chỉ cài package của container đó: image API không có PyMuPDF hay Tesseract, image index không có parser.

Không có worker điều phối riêng. Code workflow chạy trong tiến trình `worker index`, tiến trình này poll hai task queue `ingest-tq` và `index-tq`. Cấu hình Temporal và cách nâng từ 1.25 xem [deploy/temporal/README.md](deploy/temporal/README.md).

## Lệnh CLI

```bash
uv run ingest upload <file>
uv run ingest status <id>
uv run ingest list
uv run ingest review <id> approve    # hoặc reject
uv run ingest reindex <id>
uv run ingest cancel <id>
```

`review` dùng khi workflow đang chờ ở trạng thái NEEDS_REVIEW (bật bằng `INGEST_REVIEW_ENABLED=true`).

## Giao diện web

Giao diện là React SPA trong `web/`. API phục vụ bản build ở `/` (các route `/files`, `/files/<doc_id>`, `/search`, `/queues` cũng trả về SPA). Chưa build thì `/` rơi về trang tĩnh cũ `static/index.html`.

Trang `/queues` hiện các task queue của Temporal: worker nào đang nghe, bao nhiêu task đang chờ, workflow nào đang chạy và activity nào của nó đang chờ hay đang chạy. Dữ liệu lấy từ `GET /temporal/queues`. Header trang nào cũng có một dòng tóm tắt, chấm đỏ nghĩa là queue thiếu worker.

```bash
cd web
npm install
npm run build     # ra packages/api/src/ingest/api/static/dist, rồi mở http://localhost:8000
npm run dev       # Vite dev server, proxy các lời gọi API sang localhost:8000
npm test          # vitest
npm run lint && npm run typecheck
```

Image Docker target `api` tự build `web/` ở stage riêng nên không cần chạy `npm run build` trước.

Màn hình gồm Tổng quan, Tài liệu (upload, luôn xử lý theo v2; lọc; Dừng), trang chi tiết (timeline, Markdown, Chunk, Thông tin, Duyệt/Từ chối khi chờ review) và Tìm kiếm thử. Giao diện không có nút Re-index: việc này chỉ cần khi admin đổi model embedding hoặc cấu hình chunk, nên admin chạy `uv run ingest reindex <id>`.

## Endpoint API

| Endpoint | Việc |
|---|---|
| `POST /documents`, `POST /documents/batch` | Upload (form `file`) |
| `GET /documents`, `GET /documents/{id}`, `GET /stats` | Danh sách, chi tiết kèm tiến độ, số liệu tổng quan |
| `GET /documents/{id}/markdown`, `/chunks`, `/raw` | Markdown cuối, chunk (phân trang, chọn `version`), tải file gốc |
| `POST /documents/{id}/review?decision=approve\|reject`, `/reindex`, `/cancel` | Duyệt, re-index, dừng một tài liệu |
| `POST /documents/cancel-running` | Dừng mọi tài liệu đang chạy |
| `POST /search` | Tìm thử: `{query, top_k, doc_id?}`, trả 503 khi Qdrant hoặc embedding không sẵn sàng |

## Test

```bash
uv run pytest
```

Test dùng bản giả của storage, embedder và OCR, DB chạy sqlite, nên không cần Docker. Test workflow cần tải Temporal test server ở lần chạy đầu.

## Extras

```bash
uv sync --extra docling
```

`docling` thêm parser nặng hơn. OCR dùng Tesseract cài ngoài Python, cần gói `vie` (macOS: `brew install tesseract tesseract-lang`, Debian: `apt install tesseract-ocr tesseract-ocr-vie`).

## Nguồn mã

Một phần mã lấy từ [rag-starter](https://github.com/KashifAgha/rag-starter) (MIT). Chi tiết trong [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
