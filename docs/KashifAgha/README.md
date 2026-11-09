# Kiến trúc và mã nguồn RAG Starter (KashifAgha/rag-starter)

Thư mục này lưu trữ mô hình kiến trúc C4 và mã nguồn tham khảo của repository [KashifAgha/rag-starter](https://github.com/KashifAgha/rag-starter).

## Cấu trúc thư mục

- [`c4-model.md`](c4-model.md): Tài liệu phân tích kiến trúc theo mô hình C4 (Level 1 System Context, Level 2 Container, luồng Ingestion/Chat và Level 3 Component).
- [`architecture/`](architecture/):
  - [`architecture/workspace.dsl`](architecture/workspace.dsl): Mô hình kiến trúc gốc viết bằng Structurizr DSL.
  - [`architecture/render.sh`](architecture/render.sh): Script Docker kết xuất DSL ra PlantUML, SVG và PNG.
  - [`architecture/diagrams/`](architecture/diagrams/): Thư mục chứa các sơ đồ kiến trúc đã render.
- [`rag-starter/`](rag-starter/): Mã nguồn dự án `rag-starter` phục vụ chạy thử nghiệm cục bộ và đối chiếu triển khai.

## Kết xuất lại sơ đồ kiến trúc

Yêu cầu Docker đã được khởi động trên máy:

```bash
./docs/KashifAgha/architecture/render.sh
```
