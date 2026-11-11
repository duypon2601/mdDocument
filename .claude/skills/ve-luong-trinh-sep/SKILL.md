---
name: ve-luong-trinh-sep
description: |
  Vẽ luồng xử lý dạng ASCII, ít chữ, để trình bày cho sếp hoặc người không đọc code.
  Dùng khi người dùng nói "vẽ luồng trình sếp", "vẽ luồng cho sếp", "vẽ workflow dễ hiểu",
  "vẽ ascii luồng", hoặc muốn tóm một workflow (Temporal, pipeline, API) thành sơ đồ
  từng bước có vào/ra viết bằng lời thường.
---

# Vẽ luồng trình sếp

Kết quả là hai khối ASCII trả thẳng trong chat, không tạo file, không tạo trang HTML.

1. Luồng các bước, mỗi bước một hộp, bên phải ghi `vào:` và `ra:`.
2. Hình nhỏ "ai làm việc" (với Temporal: API, Temporal, các worker).

Sau hai khối chỉ thêm một hai câu về chuyện lỗi và làm lại. Không thêm gì nữa.

## Trước khi vẽ

Đọc code thật để lấy đúng thứ tự bước và chỗ chạy song song. Với dự án này:

- Workflow: `packages/index/src/ingest/index/workflows/ingestion.py`
- Input/output từng bước: `packages/core/src/ingest/core/models.py`
- Worker nào nhận bước nào: `packages/convert/src/ingest/convert/worker.py`, `packages/index/src/ingest/index/worker.py`

Không vẽ bước không có trong code. Bước tùy chọn hoặc mặc định đang tắt (ví dụ duyệt tay khi OCR kém) thì bỏ, trừ khi người dùng hỏi.

## Quy tắc chữ

Người đọc không biết tên hàm, tên class, tên queue. Viết như kể cho người ngoài nghề.

- Tên bước: 2 đến 4 chữ tiếng Việt, động từ đứng đầu. "Xem loại file", "Lấy chữ", "OCR trang ảnh", "Ghép lại", "Cắt nhỏ", "Đổi thành vector", "Xong".
- Không ghi tên activity (`detect_format`), tên dataclass (`FormatInfo`), tên queue (`convert-tq`), timeout, số lần retry, key trên storage.
- `vào:` và `ra:` mỗi dòng tối đa khoảng 35 ký tự, nói dữ liệu là gì chứ không nói kiểu dữ liệu. Đúng: "ra : 1 file Markdown hoàn chỉnh". Sai: "ra : FinalizeResult{md_key, char_count}".
- Giữ tiếng Anh cho vài từ nhóm quen dùng: OCR, Markdown, chunk, vector, worker, Qdrant, Temporal, API. Lần đầu dùng chunk thì kèm lời thường: "nhiều đoạn ngắn (chunk)".
- Không đưa số ví dụ (số trang, số chunk) vào sơ đồ.

## Mẫu luồng các bước

Đánh số từ 0. Hộp rộng cố định, cột `vào:`/`ra:` thẳng hàng. Chạy song song thì tách nhánh, ghi `(chạy song song)` ở dòng tách, rồi gom lại.

```
  Người dùng upload file
          │
          ▼
  ┌─────────────────┐   vào: file PDF/Word/Excel/ảnh
  │ 0. Nhận file    │   ra : mã tài liệu, file cất vào kho
  └────────┬────────┘
           ▼
  ┌─────────────────┐   vào: file
  │ 1. Xem loại file│   ra : loại file, trang nào cần OCR
  └────────┬────────┘
       ┌───┴────────────┐        (chạy song song)
       ▼                ▼
  ┌──────────┐    ┌──────────┐
  │ 2a. Lấy  │    │ 2b. OCR  │   vào: file
  │  chữ     │    │ trang ảnh│   ra : các đoạn chữ
  └────┬─────┘    └────┬─────┘
       └───────┬───────┘
               ▼
  ┌─────────────────┐   vào: các đoạn chữ
  │ 3. Ghép lại     │   ra : 1 file Markdown hoàn chỉnh
  └────────┬────────┘
           ▼
  ┌─────────────────┐   vào: Markdown
  │ 4. Cắt nhỏ      │   ra : nhiều đoạn ngắn (chunk)
  └────────┬────────┘
       ┌───┴───┬───────┐       (chạy song song)
       ▼       ▼       ▼
  ┌─────────────────────────┐ vào: các chunk
  │ 5. Đổi thành vector     │ ra : vector lưu vào Qdrant
  └────────────┬────────────┘
               ▼
  ┌─────────────────┐
  │ 6. Xong         │   tài liệu tìm kiếm được
  └─────────────────┘
```

## Mẫu "ai làm việc"

Câu dẫn một dòng, rồi hình. Mỗi worker ghi việc nó làm bằng lời thường và dải bước (số khớp với luồng ở trên).

Temporal đứng sau điều phối, không làm việc nặng:

```
  API ──"bắt đầu"──▶ Temporal (danh sách việc)
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
     Worker điều    Worker đổi     Worker tạo
     phối (1→6)     file (1→3)     vector (4→5)
```

## Câu kết

Tối đa hai câu, nói chuyện lỗi và chạy lại bằng lời thường, ví dụ:

> Mỗi bước nếu lỗi thì Temporal tự cho làm lại. Máy chết giữa chừng thì bước đó được giao cho worker khác, các bước đã xong không phải làm lại.

## Kiểm tra trước khi gửi

- Mỗi dòng trong khối ASCII không quá khoảng 70 ký tự để không bị cuộn ngang.
- Các cạnh hộp thẳng hàng; ký tự `│ ┌ ┐ └ ┘ ├ ┴ ┬ ▼ ▶` dùng nhất quán.
- Đọc lại: còn tên hàm, tên class, số timeout nào không? Còn thì đổi sang lời thường hoặc xoá.
- Người dùng chê nhiều chữ thì cắt tiếp `vào:`/`ra:` trước, giữ nguyên các hộp.
