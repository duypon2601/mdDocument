# Hướng dẫn cho Claude trong dự án này

## Viết tài liệu

Mọi tài liệu trong `docs/` (và README, ghi chú thiết kế) phải đọc như người viết, không như chatbot.

- Sau khi viết hoặc sửa một tài liệu, chạy skill `humanizer` (`.claude/skills/humanizer/`) trên phần văn xuôi vừa đổi trước khi báo xong.
- Skill viết bằng tiếng Anh nhưng áp dụng cho tiếng Việt: tìm cấu trúc tương đương (ví dụ "không chỉ X mà còn Y", câu chốt một dòng, liệt kê ba cho đủ bộ, nhãn in đậm kèm dấu hai chấm, từ dịch máy như "nguồn sự thật", "đóng vai trò then chốt").
- Chỉ sửa câu chữ. Không thêm hay bớt dữ kiện, số liệu, tên công nghệ. Không đụng vào code block, bảng cấu hình, sơ đồ và tên định danh.
- Thuật ngữ kỹ thuật quen dùng trong nhóm (chunk, embedding, job, worker, re-index…) giữ nguyên tiếng Anh.

## Sơ đồ kiến trúc

- Nguồn duy nhất: `docs/architecture/workspace.dsl` (Structurizr DSL). Dùng skill `c4-architecture` hoặc lệnh `/c4`.
- Sửa `.dsl` rồi chạy `./docs/architecture/render.sh` (cần Docker). Không sửa ảnh trong `docs/architecture/diagrams/` bằng tay.
