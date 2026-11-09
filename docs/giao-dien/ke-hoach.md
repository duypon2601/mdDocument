# Kế hoạch giao diện web

Trang `packages/api/src/ingest/api/static/index.html` hiện tại làm được việc upload, xem danh sách, xem Markdown, duyệt và huỷ. Bản mới viết lại bằng React và thêm những phần còn thiếu: re-index, lọc theo trạng thái, phân trang, timeline các bước, xem chunk, tìm kiếm ngữ nghĩa thử, tải file gốc, trang tổng quan và nút dừng.

File này chia việc thành 8 session cho Sonnet 5.5. Mỗi session mở bằng prompt ở cuối file, làm xong thì commit rồi mới sang session sau.

## Quyết định đã chốt

| Mục | Chọn |
|---|---|
| Stack | React 19 + Vite + TypeScript, thư mục `web/` ở gốc repo |
| Style | Tailwind CSS v4, không dùng thư viện component nặng |
| Gọi API | TanStack Query (polling bằng `refetchInterval`), client `fetch` có kiểu |
| Router | React Router, history mode |
| Markdown | `react-markdown` + `remark-gfm` + `rehype-sanitize` |
| Test | Vitest + Testing Library + MSW ở frontend, pytest ở backend |
| Phục vụ | `npm run build` ra `packages/api/src/ingest/api/static/dist/`, FastAPI trả file này |

`web/` không nằm trong `packages/` vì `[tool.uv.workspace] members = ["packages/*"]` sẽ coi mọi thư mục con là package Python và báo lỗi khi thiếu `pyproject.toml`.

Khi chưa build `dist/`, FastAPI vẫn trả trang `index.html` cũ ở `/`, nên test Python và máy không cài Node vẫn chạy được.

Package `api` không được import `ingest.index` (`tests/test_package_boundaries.py`). Vì vậy tìm kiếm có client embedding và Qdrant riêng trong `ingest.api.search`, chỉ thêm dependency `qdrant-client` và `httpx` cho `ingest-api`.

"Dừng" là huỷ workflow qua `POST /documents/{id}/cancel` đã có. Thêm nút dừng tất cả tài liệu đang chạy.

## Màn hình

Đường dẫn SPA không trùng route API: API dùng `/documents/...`, `/search`, `/stats`, Swagger dùng `/docs`.

| Đường dẫn | Màn hình | Nội dung |
|---|---|---|
| `/` | Tổng quan | Thẻ đếm theo trạng thái, tổng chunk, 5 tài liệu mới nhất, nút "Dừng tất cả đang chạy" |
| `/files` | Tài liệu | Vùng upload (chọn profile v2 / v1 / bản cũ, nhiều file), tab lọc trạng thái, ô tìm tên, bảng có phân trang, nút trên từng dòng |
| `/files/:docId` | Chi tiết | Tiêu đề, nút hành động, timeline các bước, tab Markdown / Chunk / Thông tin |
| `/search` | Tìm kiếm thử | Ô câu hỏi, top_k, lọc theo tài liệu, danh sách kết quả có điểm số |

Nút hành động theo trạng thái:

| Trạng thái | Nút |
|---|---|
| RECEIVED, CONVERTING, CONVERTED, INDEXING | Dừng |
| NEEDS_REVIEW | Duyệt, Từ chối, Dừng |
| INDEXED | Re-index, Tải Markdown |
| FAILED, CANCELLED | (upload lại cùng file để chạy lại) |
| Mọi trạng thái | Tải file gốc |

Dừng và Từ chối hỏi xác nhận bằng dialog trong trang, không dùng `window.confirm`.

Timeline: RECEIVED → CONVERTING → (NEEDS_REVIEW nếu có) → CONVERTED → INDEXING → INDEXED. Bước hiện tại lấy từ `progress` nếu có, không thì từ `status`. FAILED, CANCELLED tô đỏ ở bước đang dở.

Polling giống trang cũ: có tài liệu đang chạy thì 2 giây một lần, không thì 15 giây.

## API cần thêm (hợp đồng chung cho backend và frontend)

Session frontend mock API bằng MSW theo đúng dạng dưới đây, nên backend phải trả khớp từng field.

### Đã có

```
POST /documents                    multipart: file, extract_media, pipeline_version → 202 | 200 (duplicate)
POST /documents/batch              multipart: files[] ...                          → {results: [...]}
GET  /documents?status&q&limit&offset                                              → {items, total, limit, offset}
GET  /documents/{id}                                                               → Document + progress
GET  /documents/{id}/markdown                                                      → text/markdown
POST /documents/{id}/review?decision=approve|reject
POST /documents/{id}/reindex                                                       → 202 {doc_id, index_version}
POST /documents/{id}/cancel                                                        → 202 {doc_id, cancel_requested}
```

Document: `doc_id, file_name, mime, size, status, error_code, chunk_count, index_version, embedding_model, created_at, updated_at, extract_media, profile ("legacy"|"v1"|"v2")`. `created_at`/`updated_at` có thể thiếu múi giờ, frontend coi là UTC.

Lỗi: `{"detail": "..."}` hoặc `{"code": "...", "detail": "..."}`.

### Mới

```
GET /documents?status=A,B          status nhận danh sách cách nhau bằng dấu phẩy (giữ tương thích một giá trị)

GET /stats
→ {"total": 12, "chunks": 340, "by_status": {"RECEIVED": 0, ..., "CANCELLED": 1}}
  by_status có đủ 8 trạng thái trong STATUSES, thiếu thì 0

GET /documents/{id}/raw
→ bytes file gốc, Content-Type = mime, Content-Disposition: attachment; filename*=UTF-8''<tên>
  404 nếu không có tài liệu hoặc không có file

GET /documents/{id}/chunks?version=&offset=0&limit=50   (limit 1..200, version mặc định = index_version)
→ {"doc_id", "index_version", "total", "offset", "limit",
   "items": [{"chunk_index", "text", "heading_path", "page_start", "page_end", "content_hash"}]}
  Đọc chunks/{doc_id}/v{n}/batch-*.jsonl, sắp batch theo số (batch-10 sau batch-9), items theo chunk_index.
  404 nếu không có file chunk của version đó.

POST /documents/cancel-running
→ 202 {"requested": ["<doc_id>", ...], "failed": [{"doc_id", "detail"}]}
  Huỷ mọi tài liệu có status trong RUNNING_STATUSES. Lỗi của một tài liệu không chặn các tài liệu khác.

POST /search   JSON {"query": str 1..2000 ký tự, "top_k": 1..50 (mặc định 8), "doc_id": str | null}
→ {"query", "model", "results": [{"score", "doc_id", "file_name", "index_version", "chunk_index",
                                   "heading_path", "page_start", "page_end", "text"}]}
  Collection chưa có thì results = [].
  503 {"code": "SEARCH_UNAVAILABLE", "detail"} khi chưa cấu hình searcher hoặc embedder/Qdrant lỗi.
```

## Chia session

| # | Session | Phụ thuộc | Chạy song song được với |
|---|---|---|---|
| 1 | Backend: stats, raw, chunks, status nhiều giá trị, cancel-running | | 2, 3 |
| 2 | Backend: tìm kiếm ngữ nghĩa | | 1, 3 |
| 3 | Frontend nền: scaffold, layout, API client, FastAPI phục vụ SPA, Docker | | 1, 2 |
| 4 | Màn hình Tài liệu + upload | 3 | |
| 5 | Màn hình Chi tiết: timeline, hành động, Markdown, Thông tin | 4 | |
| 6 | Tab Chunk + màn hình Tìm kiếm thử | 5 | |
| 7 | Tổng quan + dừng tất cả + hoàn thiện (dark mode, mobile, a11y, trạng thái rỗng/lỗi) | 6 | |
| 8 | Chạy thật end-to-end, cập nhật README, C4, xoá trang cũ hay không | 1–7 | |

Session 1, 2, 3 đụng vào file khác nhau. Có thể mở ba cửa sổ cùng lúc, mỗi cửa sổ một git worktree. Session 1 và 2 cùng sửa `app.py`, nên merge cái sau thì rebase lại.

## Quy ước chung cho mọi session

- Đọc `CLAUDE.md` và file này trước khi code.
- Chữ trên giao diện bằng tiếng Việt. Nhãn trạng thái giữ như trang cũ: Đã nhận, Đang chuyển đổi, Chờ duyệt OCR, Đã chuyển đổi, Đang index, Hoàn tất, Lỗi, Đã huỷ.
- Không đổi hành vi endpoint đã có, trừ phần ghi rõ ở trên.
- Backend xong phải qua: `uv run pytest` và `uv run ruff check . && uv run ruff format --check .`
- Frontend xong phải qua: `cd web && npm run lint && npm run typecheck && npm test && npm run build`
- Mỗi session một nhánh `ui/s<N>-<tên>`, commit nhỏ theo từng bước, không push nếu chưa được bảo.
- Sửa tài liệu trong `docs/` hay README thì chạy skill `humanizer` trên phần văn xuôi vừa sửa.

---

## Prompt cho từng session

Dán nguyên khối vào session mới (`claude --model sonnet` hoặc `/model sonnet`).

### Session 1: API bổ sung

```
Đọc CLAUDE.md và docs/giao-dien/ke-hoach.md (mục "API cần thêm"). Làm Session 1.

Việc:
1. ingest.core.db.DocumentRepository:
   - list(): tham số status nhận str | list[str] | None; list thì dùng IN.
   - thêm stats() -> tuple[int, int, dict[str, int]]: tổng tài liệu, tổng chunk_count,
     đếm theo status (đủ 8 khoá STATUSES, thiếu thì 0). Một query GROUP BY.
2. packages/api/src/ingest/api/app.py:
   - GET /documents: tách status theo dấu phẩy, mỗi giá trị phải nằm trong STATUSES, sai thì 422.
   - GET /stats.
   - GET /documents/{doc_id}/raw: storage.get(keys.raw_key(doc_id, rec.file_name)),
     Content-Disposition dùng filename* mã hoá UTF-8 (tên tiếng Việt).
   - GET /documents/{doc_id}/chunks: đọc storage.list_keys(f"chunks/{doc_id}/v{version}/"),
     sắp theo số batch, ghép dòng jsonl, cắt theo offset/limit. Format dòng xem
     packages/index/src/ingest/index/activities.py hàm chunk_markdown. Không import ingest.index.
   - POST /documents/cancel-running: khai báo trước các route /documents/{doc_id}/...,
     duyệt repo.list(status=list(RUNNING_STATUSES)) theo trang, gọi wf.cancel từng cái,
     gom lỗi vào "failed".
3. Test trong tests/test_api.py (dùng fixture env, FakeWf, MemoryStorage có sẵn):
   status nhiều giá trị + 422; stats đủ khoá; raw đúng bytes + header tên tiếng Việt + 404;
   chunks với 12 batch để bắt lỗi sắp xếp chuỗi, phân trang, version, 404;
   cancel-running với một tài liệu làm FakeWf ném lỗi.
4. Cập nhật CLI nếu thấy tiện (không bắt buộc).

Xong khi: uv run pytest xanh, ruff sạch, test_package_boundaries vẫn qua. Commit trên nhánh ui/s1-api.
```

### Session 2: Tìm kiếm ngữ nghĩa

```
Đọc CLAUDE.md và docs/giao-dien/ke-hoach.md (mục "API cần thêm", POST /search). Làm Session 2.

Ràng buộc: package api KHÔNG được import ingest.index (tests/test_package_boundaries.py).

Việc:
1. packages/api/pyproject.toml: thêm "httpx", "qdrant-client". Chạy uv lock.
2. packages/api/src/ingest/api/search.py:
   - Protocol Searcher: search(query: str, top_k: int, doc_id: str | None) -> dict
     (dạng response ở kế hoạch).
   - QdrantSearcher(qdrant_client, collection, embed_base_url, embed_api_key, embed_model):
     embed 1 câu bằng httpx POST {base}/embeddings (giống OpenAICompatEmbedder ở
     packages/index/src/ingest/index/embedder.py, viết lại gọn, không import),
     rồi client.query_points(collection, query=vec, limit=top_k, query_filter theo doc_id nếu có,
     with_payload=True). Bỏ point dấu vân tay (id 00000000-0000-5000-8000-000000000001,
     xem vectorstore.py) bằng filter must_not has_id hoặc lọc sau.
     Collection chưa tồn tại thì trả results rỗng.
   - SearchUnavailable exception.
3. app.py: create_app thêm tham số searcher: Searcher | None = None. POST /search dùng
   pydantic model cho body. searcher None hoặc ném SearchUnavailable/httpx lỗi → 503
   {"code": "SEARCH_UNAVAILABLE", "detail": ...}. Chạy search trong threadpool (hàm sync).
   create_default_app dựng QdrantSearcher từ Settings (qdrant_url, qdrant_collection, embed_*).
   _LazyWorkflowClient không đụng tới.
4. Test tests/test_search.py: QdrantClient(":memory:"), embed giả bằng httpx.MockTransport
   (cho QdrantSearcher nhận tham số http_client tuỳ chọn để test), nạp vài point đúng payload
   như activities.embed_and_upsert, kiểm tra thứ tự điểm, lọc doc_id, bỏ point vân tay,
   collection thiếu → rỗng, 422 khi query rỗng hoặc top_k > 50, 503 khi searcher None.

Xong khi: uv run pytest xanh, ruff sạch, docker build --target api . vẫn build được
(nếu có Docker). Commit trên nhánh ui/s2-search.
```

### Session 3: Nền frontend

```
Đọc CLAUDE.md và docs/giao-dien/ke-hoach.md (toàn bộ). Làm Session 3. Dùng skill
agent-skills:frontend-ui-engineering.

Việc:
1. Tạo web/ bằng Vite (React + TS), npm. Cài: react-router, @tanstack/react-query,
   tailwindcss v4 (@tailwindcss/vite), react-markdown, remark-gfm, rehype-sanitize,
   vitest, @testing-library/react, @testing-library/user-event, jsdom, msw, eslint.
   Script: dev, build, lint, typecheck (tsc --noEmit), test (vitest run).
2. vite.config.ts: build.outDir = ../packages/api/src/ingest/api/static/dist, emptyOutDir;
   dev server proxy /documents, /search, /stats → http://localhost:8000.
3. web/src/api/: types.ts (Document, DocumentList, Stats, ChunkPage, SearchResponse,
   Status, Profile đúng hợp đồng trong kế hoạch, gồm cả endpoint mới), client.ts (hàm fetch
   có kiểu, lỗi ném ApiError{status, code, detail}), hooks.ts (useDocuments, useDocument,
   useStats, useMarkdown, useChunks, useSearch, mutation upload/review/reindex/cancel/
   cancelRunning; refetchInterval 2000 khi có tài liệu đang chạy, 15000 khi không).
   web/src/lib/: status.ts (nhãn tiếng Việt, nhóm running/ok/bad), format.ts (size,
   thời gian coi chuỗi không có múi giờ là UTC, giống hàm when() ở trang cũ).
4. Layout: thanh điều hướng (Tổng quan, Tài liệu, Tìm kiếm thử), 4 route với trang
   placeholder, trang 404. Token màu trong CSS, có dark mode theo prefers-color-scheme.
   Component dùng chung: StatusPill, Button, ConfirmDialog (dùng <dialog>), Toast,
   EmptyState, ErrorState.
5. web/src/test/: MSW handlers cho mọi endpoint (cả endpoint mới) với dữ liệu mẫu,
   setup cho vitest. Test cho client.ts, format.ts, status.ts, StatusPill, ConfirmDialog.
6. FastAPI (packages/api/src/ingest/api/app.py): nếu static/dist/index.html tồn tại thì
   mount /assets và trả dist/index.html cho GET /, /files, /files/{path:path}, /search;
   không thì giữ trang cũ ở /. Test cả hai trường hợp (tạo dist giả trong tmp_path,
   cho create_app nhận tham số static_dir tuỳ chọn).
7. .gitignore: web/node_modules, packages/api/src/ingest/api/static/dist.
8. Dockerfile: stage node:22-slim build web/, target api COPY dist vào đúng chỗ.
   .dockerignore bỏ web/node_modules.

Xong khi: lệnh kiểm tra frontend và backend trong kế hoạch đều qua; uv run ingest api rồi
mở http://localhost:8000/files thấy layout mới, F5 không 404. Commit trên nhánh ui/s3-web-base.
```

### Session 4: Màn hình Tài liệu

```
Đọc CLAUDE.md, docs/giao-dien/ke-hoach.md, rồi xem web/src (nền từ Session 3) và trang cũ
packages/api/src/ingest/api/static/index.html để giữ hành vi. Làm Session 4.

Việc ở route /files:
1. UploadPanel: chọn profile (v2 mặc định / v1 / bản cũ, nhớ lựa chọn bằng localStorage
   bọc try/catch), kéo thả hoặc chọn nhiều file, dùng được bằng bàn phím. Upload từng file
   (POST /documents, extract_media = profile !== "legacy", pipeline_version = profile ===
   "v1" ? 1 : 2), hiện danh sách tiến trình từng file: đang gửi / đã nhận / trùng (dùng lại
   kết quả) / lỗi kèm detail. Xong thì invalidate danh sách.
2. Bộ lọc: tab Tất cả / Đang chạy (5 trạng thái RUNNING, gửi status=A,B,...) / Chờ duyệt /
   Hoàn tất / Lỗi / Đã huỷ; ô tìm tên debounce 300ms. Lọc, trang, từ khoá nằm trên URL
   query (?status=&q=&page=) để F5 và chia sẻ link giữ nguyên.
3. Bảng: tên file + tag profile, kích thước, trạng thái, số chunk, cập nhật lúc; bấm dòng
   mở /files/:docId. Phân trang 20 dòng, có tổng số. Mobile: bảng chuyển thành danh sách thẻ.
4. Nút trên dòng: Dừng (khi đang chạy, có ConfirmDialog), Re-index (khi INDEXED).
   Kết quả báo bằng Toast.
5. Test: upload thành công/trùng/lỗi 413, đổi profile gửi đúng form field, lọc ghi vào URL,
   phân trang, nút Dừng gọi đúng endpoint sau khi xác nhận.

Xong khi: lệnh kiểm tra frontend qua; chạy với API thật upload được samples/*.pdf và thấy
trạng thái tự đổi. Commit trên nhánh ui/s4-files.
```

### Session 5: Màn hình Chi tiết

```
Đọc CLAUDE.md, docs/giao-dien/ke-hoach.md (mục Màn hình, bảng nút theo trạng thái,
Timeline), rồi xem web/src. Làm Session 5.

Việc ở route /files/:docId:
1. Header: tên file, tag profile, StatusPill, nút theo bảng trạng thái trong kế hoạch.
   Tải file gốc là link <a href="/documents/{id}/raw" download>. Tải Markdown tạo Blob từ
   /markdown. Duyệt/Từ chối/Dừng/Re-index qua mutation, Từ chối và Dừng có ConfirmDialog.
   Mutation xong thì invalidate tài liệu và danh sách.
2. Timeline ngang (dọc trên mobile) theo kế hoạch. Chỉ hiện bước NEEDS_REVIEW khi tài liệu
   đang hoặc đã ở bước đó (đoán từ status/progress). Có aria-current="step".
3. Tab (URL hash hoặc ?tab=): Markdown | Chunk | Thông tin. Chunk để placeholder cho
   Session 6.
   - Markdown: bỏ front-matter, render bằng react-markdown + remark-gfm + rehype-sanitize,
     bảng cuộn ngang được, nút chuyển "Xem gốc" (pre). Đang chạy thì báo "Markdown sẽ hiện
     khi chuyển đổi xong", FAILED thì báo lỗi kèm error_code. 404 không phải lỗi đỏ.
   - Thông tin: doc_id đầy đủ (nút copy), mime, kích thước, profile, index_version,
     embedding_model, chunk_count, error_code, tạo lúc, cập nhật lúc.
4. doc_id không tồn tại → trang "Không tìm thấy tài liệu" có link về /files.
5. Test: nút đúng theo từng trạng thái (table-driven), timeline đúng bước, Markdown render
   bảng và loại script độc (sanitize), 404.

Xong khi: lệnh kiểm tra frontend qua; với API thật mở samples/bao-cao-tai-chinh.xlsx đã
INDEXED thấy bảng render đúng. Commit trên nhánh ui/s5-detail.
```

### Session 6: Chunk và Tìm kiếm thử

```
Đọc CLAUDE.md, docs/giao-dien/ke-hoach.md (GET /documents/{id}/chunks, POST /search),
rồi xem web/src. Session 1 và 2 phải đã merge. Làm Session 6.

Việc:
1. Tab Chunk ở /files/:docId: danh sách thẻ, mỗi thẻ có #chunk_index, heading_path,
   trang page_start–page_end (bỏ nếu 0), text rút gọn 6 dòng có nút "Xem hết". Phân trang
   50. Chọn version nếu index_version > 1 (chỉ version hiện tại thường còn file, version
   cũ 404 thì báo "Đã dọn sau re-index"). Tài liệu chưa INDEXED thì báo chưa có chunk.
2. Route /search: ô câu hỏi (Enter để tìm), top_k (5/8/20), chọn lọc theo một tài liệu
   (combobox lấy từ GET /documents?status=INDEXED&limit=200, nhận cả ?doc_id= trên URL).
   Query và tham số lưu trên URL. Kết quả: điểm (2 chữ số), tên file (link sang chi tiết),
   heading_path, trang, đoạn text có highlight từ khoá thô. 503 → thông báo "Chưa bật tìm
   kiếm: kiểm tra Qdrant và endpoint embedding" kèm detail. Kết quả rỗng có EmptyState.
3. Ở trang chi tiết tài liệu INDEXED thêm nút "Tìm trong tài liệu này" mở /search?doc_id=.
4. Test: phân trang chunk, version cũ 404, search gửi đúng body, 503, highlight không
   chèn HTML thô (an toàn XSS).

Xong khi: lệnh kiểm tra frontend qua; với API thật + Ollama bge-m3, tìm câu trong
samples/hop-dong-scan.pdf ra đúng tài liệu ở top đầu. Commit trên nhánh ui/s6-chunks-search.
```

### Session 7: Tổng quan và hoàn thiện

```
Đọc CLAUDE.md, docs/giao-dien/ke-hoach.md, rồi xem web/src. Làm Session 7. Dùng skill
agent-skills:frontend-ui-engineering.

Việc:
1. Route /: thẻ số theo trạng thái từ GET /stats (bấm thẻ mở /files?status=...), tổng chunk,
   5 tài liệu mới nhất, thẻ "Đang chạy" nổi bật. Nút "Dừng tất cả đang chạy" (chỉ hiện khi
   có tài liệu chạy) → ConfirmDialog ghi rõ số tài liệu → POST /documents/cancel-running →
   Toast báo số đã gửi lệnh và liệt kê lỗi nếu có. Thêm nút này ở /files khi tab Đang chạy.
2. Rà toàn bộ app:
   - Dark mode đủ mọi màn hình, tương phản chữ đạt WCAG AA.
   - Ở 375px: không cuộn ngang trang, gutter 16px, nav gọn.
   - Bàn phím: tab đi hết nút, focus ring rõ, dialog bẫy focus và Esc đóng.
   - Mọi truy vấn có trạng thái đang tải (skeleton), lỗi (ErrorState có nút thử lại), rỗng.
   - API mất kết nối: banner "Mất kết nối API" và tự hết khi có lại.
   - Tiêu đề tab trình duyệt đổi theo trang.
3. Test: dashboard đếm đúng, dừng tất cả, banner mất kết nối.
4. Chạy agent-skills:code-review-and-quality trên toàn bộ web/ rồi sửa vấn đề mức cao.

Xong khi: lệnh kiểm tra frontend qua; npm run build không có cảnh báo chunk > 500 kB
(tách route bằng lazy nếu cần). Commit trên nhánh ui/s7-dashboard-polish.
```

### Session 8: Kiểm tra end-to-end và tài liệu

```
Đọc CLAUDE.md, docs/giao-dien/ke-hoach.md. Mọi session 1–7 đã merge vào main. Làm Session 8.

Việc:
1. Dựng hệ thống thật theo README (docker compose up -d, 2 worker, api; cd web && npm run
   build). Dùng skill run hoặc claude-in-chrome đi hết luồng: upload 4 file trong samples/
   với cả 3 profile, xem timeline chạy, Dừng một file giữa chừng, bật INGEST_REVIEW_ENABLED
   để thử Duyệt/Từ chối, Re-index một file, xem Chunk, Tìm kiếm thử, tải file gốc, Dừng tất
   cả. Ghi lỗi gặp được, sửa, thêm test cho từng lỗi.
2. Kiểm tra docker compose --profile app up -d --build: image api có dist, mở :8000 thấy
   giao diện mới.
3. README: mục chạy giao diện (npm install, npm run dev qua proxy, npm run build), endpoint
   mới. docs/c4-model.md: cập nhật dòng Web UI / CLI (React SPA build tĩnh do API phục vụ)
   và component mới của Backend API (Search). Sửa docs/architecture/workspace.dsl theo
   skill c4-architecture rồi chạy ./docs/architecture/render.sh. Chạy skill humanizer trên
   phần văn xuôi vừa sửa.
4. Hỏi user có xoá trang static/index.html cũ không (nó vẫn là fallback khi chưa build).

Xong khi: luồng ở bước 1 chạy hết không lỗi console, mọi lệnh kiểm tra qua, tài liệu đã cập
nhật. Commit trên nhánh ui/s8-e2e-docs.
```
