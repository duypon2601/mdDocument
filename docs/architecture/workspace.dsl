workspace "Document Ingestion System" "Tài liệu đầu vào → Markdown → chunk → embedding → Vector DB, điều phối bằng Temporal" {

    !impliedRelationships true

    model {
        // ---------- Người dùng ----------
        user = person "Người dùng / Nghiệp vụ" "Tải tài liệu lên, theo dõi tiến độ, duyệt tài liệu OCR kém"
        admin = person "Quản trị viên" "Cấu hình pipeline, xem lịch sử job, retry hoặc huỷ job lỗi"

        // ---------- Hệ thống bên ngoài ----------
        source = softwareSystem "Nguồn tài liệu" "File share, SharePoint, Google Drive, email… (tùy chọn, đồng bộ tự động)" "External"
        embed = softwareSystem "Embedding Model Provider" "API hoặc model local tạo vector (OpenAI, Voyage, bge-m3…)" "External"
        ocr = softwareSystem "OCR / Vision Model" "Đọc chữ từ ảnh và PDF scan (Tesseract, PaddleOCR hoặc VLM)" "External"
        rag = softwareSystem "Ứng dụng RAG / Search" "Chatbot, trích xuất thông tin, tìm kiếm ngữ nghĩa" "External"

        // ---------- Hệ thống đang thiết kế ----------
        dis = softwareSystem "Document Ingestion System" "Nhận tài liệu, chuyển sang Markdown, chia chunk, tạo embedding và lưu vào Vector DB" {

            webui = container "Web UI / CLI" "Upload, xem tiến độ, duyệt tài liệu, bấm re-index" "React hoặc Typer CLI" "WebBrowser"

            api = container "Ingestion API" "Nhận file, kiểm tra, lưu bản gốc, khởi động workflow, trả trạng thái" "Python, FastAPI, temporalio client" {
                uploadCtl = component "Upload Controller" "POST /documents (multipart), POST /documents/batch" "FastAPI router"
                statusCtl = component "Status Controller" "GET /documents/{id}, POST /documents/{id}/review, /reindex, /cancel" "FastAPI router"
                validator = component "File Validator" "Kiểm tra MIME thật, dung lượng, định dạng hỗ trợ" "python-magic"
                dedup = component "Dedup Service" "Tính SHA-256, doc_id sinh từ hash nên file trùng không tạo job mới" "hashlib"
                storageCli = component "Storage Client" "Ghi file gốc vào raw/{doc_id}/" "boto3 / minio"
                docRepo = component "Document Repository" "CRUD document, trạng thái nghiệp vụ, danh sách tài liệu" "SQLAlchemy"
                wfClient = component "Workflow Client" "start_workflow(id=ingest-{doc_id}), query get_progress, signal review_decision, cancel" "temporalio.client"
            }

            temporal = container "Temporal Server" "Lưu lịch sử từng bước của workflow, quản lý task queue, timer, retry; kèm Temporal Web UI" "Temporal (self-hosted, PostgreSQL riêng) hoặc Temporal Cloud" "Temporal"

            converter = container "Conversion Worker" "Chạy activity chuyển file gốc sang Markdown. Scale theo CPU/GPU" "Python, temporalio worker, task queue convert-tq" {
                convWorker = component "Worker (convert-tq)" "Đăng ký activity convert, giới hạn số activity chạy song song theo CPU/GPU" "temporalio.worker"
                detectAct = component "detect_format" "Loại file, PDF có lớp text hay không, danh sách trang cần OCR. Trả FormatInfo nhỏ" "@activity.defn, python-magic, PyMuPDF"
                parseAct = component "parse_document" "Parse phần có text, ghi md-raw/{doc_id}/text.md" "@activity.defn"
                pdfParser = component "PDF Parser" "Giữ heading, bảng, thứ tự đọc, số trang" "Docling / PyMuPDF" "Module"
                officeParser = component "Office Parser" "DOCX, PPTX, XLSX → Markdown" "MarkItDown / python-docx / python-pptx / openpyxl" "Module"
                htmlParser = component "HTML / Text Parser" "HTML, TXT, CSV → Markdown" "markdownify / BeautifulSoup" "Module"
                ocrAct = component "ocr_pages" "OCR một lô trang (fan-out theo lô), ghi md-raw/{doc_id}/ocr/{batch}.md, heartbeat từng trang, trả điểm tin cậy" "@activity.defn"
                finalizeAct = component "finalize_markdown" "Ghép text và OCR theo thứ tự trang, chuẩn hóa heading/bảng, bỏ header/footer lặp, thêm front-matter, ghi md/{doc_id}.md" "@activity.defn, python-frontmatter"
            }

            indexer = container "Indexing Worker" "Chạy code workflow (điều phối các bước, chờ signal, ghi trạng thái) và activity chia chunk, tạo embedding, ghi Vector DB. Một tiến trình, hai Worker. Scale theo rate limit của embedding API" "Python, temporalio worker, task queue ingest-tq và index-tq" {
                wfWorker = component "Worker (ingest-tq)" "Đăng ký hai workflow và activity update_status. Không bị rate limit của index-tq" "temporalio.worker"
                ingestWf = component "DocumentIngestionWorkflow" "detect → parse / OCR → finalize → chunk → embed + upsert → cleanup. Query get_progress, signal review_decision" "@workflow.defn"
                reindexWf = component "ReindexWorkflow" "Bỏ qua bước convert: chunk → embed + upsert → cleanup với model hoặc cách chunk mới" "@workflow.defn"
                statusAct = component "update_status" "Ghi trạng thái, số chunk, mã lỗi vào Metadata DB. Ghi lại cùng giá trị không sao" "@activity.defn, SQLAlchemy"
                idxWorker = component "Worker (index-tq)" "Đăng ký activity index, giới hạn số activity mỗi giây theo rate limit embedding" "temporalio.worker"
                chunkAct = component "chunk_markdown" "Cắt theo heading rồi theo token (512, overlap 64), gắn metadata, ghi chunks/{doc_id}/v{n}/batch-{i}.jsonl, trả số lô" "@activity.defn, MarkdownHeaderTextSplitter"
                embedAct = component "embed_and_upsert" "Một lô: đọc JSONL, gọi embed, upsert với id = uuid5(doc_id, version, chunk_index). Vector không đi qua Temporal" "@activity.defn, httpx, qdrant-client"
                cleanupAct = component "cleanup_old_chunks" "Xóa point của doc_id thuộc index_version cũ" "@activity.defn, qdrant-client"
            }

            objstore = container "Object Storage" "File gốc, Markdown trung gian và cuối, chunk JSONL, ảnh trích xuất" "MinIO / S3" "Database"
            metadb = container "Metadata DB" "Danh mục tài liệu, trạng thái nghiệp vụ, hash, index_version" "PostgreSQL" "Database"
            vectordb = container "Vector DB" "Vector + payload: text chunk, doc_id, heading, trang, index_version" "Qdrant (hoặc pgvector, Milvus)" "Database"
        }

        // ---------- Level 1 ----------
        user -> dis "Upload tài liệu, xem tiến độ, duyệt" "HTTPS"
        admin -> dis "Cấu hình, re-index, xử lý job lỗi" "HTTPS"
        source -> dis "Đẩy / được kéo tài liệu mới" "Webhook / API"
        dis -> ocr "Gửi trang ảnh cần OCR" "HTTPS / local"
        dis -> embed "Gửi chunk text, nhận vector" "HTTPS / gRPC"
        rag -> dis "Truy vấn vector + Markdown gốc" "gRPC / HTTPS"

        // ---------- Level 2 ----------
        user -> webui "Upload, theo dõi, duyệt" "HTTPS"
        admin -> webui "Cấu hình, re-index" "HTTPS"
        admin -> temporal "Xem lịch sử, retry, terminate qua Temporal UI" "HTTPS"
        source -> api "Đẩy tài liệu mới" "Webhook"
        webui -> api "Gọi API" "REST/JSON"
        api -> objstore "Lưu file gốc" "S3 API"
        api -> metadb "Tạo document, đọc danh sách" "SQL"
        api -> temporal "Start workflow, query, signal, cancel" "gRPC"

        converter -> temporal "Nhận activity task, heartbeat, trả kết quả" "gRPC, convert-tq"
        converter -> objstore "Đọc file gốc, ghi Markdown" "S3 API"
        converter -> ocr "OCR trang ảnh" "HTTPS / local"

        indexer -> temporal "Nhận workflow task và activity task, trả kết quả" "gRPC, ingest-tq + index-tq"
        indexer -> metadb "Cập nhật trạng thái" "SQL"
        indexer -> objstore "Đọc Markdown, ghi/đọc chunk" "S3 API"
        indexer -> embed "Tạo embedding" "HTTPS"
        indexer -> vectordb "Upsert, xóa bản cũ" "gRPC"

        rag -> vectordb "Tìm kiếm vector" "gRPC"
        rag -> objstore "Lấy Markdown gốc khi cần" "S3 API"

        // ---------- Level 3: Ingestion API ----------
        webui -> uploadCtl "Upload file" "REST"
        webui -> statusCtl "Xem tiến độ, duyệt, re-index, huỷ" "REST"
        uploadCtl -> validator "Validate"
        uploadCtl -> dedup "Tính doc_id"
        dedup -> docRepo "Tra hash"
        uploadCtl -> storageCli "Lưu file"
        uploadCtl -> docRepo "Tạo document"
        uploadCtl -> wfClient "Khởi động ingestion"
        statusCtl -> docRepo "Đọc trạng thái"
        statusCtl -> wfClient "Query tiến độ, signal duyệt, cancel, start reindex"
        storageCli -> objstore "PUT raw" "S3 API"
        docRepo -> metadb "Đọc / ghi" "SQL"
        wfClient -> temporal "start_workflow, query, signal, cancel" "gRPC"

        // ---------- Level 3: Indexing Worker (workflow) ----------
        wfWorker -> temporal "Long-poll ingest-tq" "gRPC"
        wfWorker -> ingestWf "Chạy / replay"
        wfWorker -> reindexWf "Chạy / replay"
        wfWorker -> statusAct "Chạy"
        ingestWf -> temporal "Đặt lịch activity trên convert-tq, index-tq; chờ signal" "gRPC"
        reindexWf -> temporal "Đặt lịch activity trên index-tq" "gRPC"
        ingestWf -> statusAct "execute_activity"
        reindexWf -> statusAct "execute_activity"
        statusAct -> metadb "UPDATE status" "SQL"

        // ---------- Level 3: Conversion Worker ----------
        convWorker -> temporal "Long-poll convert-tq, heartbeat, trả kết quả" "gRPC"
        convWorker -> detectAct "Chạy"
        convWorker -> parseAct "Chạy"
        convWorker -> ocrAct "Chạy"
        convWorker -> finalizeAct "Chạy"
        detectAct -> objstore "GET raw" "S3 API"
        parseAct -> objstore "GET raw, PUT md-raw" "S3 API"
        parseAct -> pdfParser "PDF"
        parseAct -> officeParser "DOCX / PPTX / XLSX"
        parseAct -> htmlParser "HTML / TXT / CSV"
        ocrAct -> objstore "GET raw, PUT md-raw/ocr" "S3 API"
        ocrAct -> ocr "OCR từng trang" "HTTPS / local"
        finalizeAct -> objstore "GET md-raw, PUT md" "S3 API"

        // ---------- Level 3: Indexing Worker (index) ----------
        idxWorker -> temporal "Long-poll index-tq, trả kết quả" "gRPC"
        idxWorker -> chunkAct "Chạy"
        idxWorker -> embedAct "Chạy"
        idxWorker -> cleanupAct "Chạy"
        chunkAct -> objstore "GET md, PUT chunks" "S3 API"
        embedAct -> objstore "GET chunk batch" "S3 API"
        embedAct -> embed "Batch embed" "HTTPS"
        embedAct -> vectordb "Upsert" "gRPC"
        cleanupAct -> vectordb "Delete theo doc_id + version cũ" "gRPC"
    }

    views {
        properties {
            "c4plantuml.tags" "true"
        }

        systemContext dis "L1-SystemContext" "Level 1 - System Context" {
            include *
            autoLayout lr
        }

        container dis "L2-Container" "Level 2 - Container (Temporal)" {
            include *
            autoLayout lr
        }

        dynamic dis "L2-Flow-Ingestion" "Luồng xử lý một tài liệu qua Temporal" {
            webui -> api "Upload file"
            api -> objstore "PUT raw/{doc_id}/"
            api -> metadb "INSERT document (RECEIVED)"
            api -> temporal "start_workflow(id=ingest-{doc_id})"
            indexer -> temporal "Nhận workflow task (ingest-tq), đặt lịch detect / parse / OCR"
            converter -> temporal "Nhận activity convert"
            converter -> objstore "Đọc raw, ghi md/{doc_id}.md"
            converter -> ocr "OCR trang scan (nếu có)"
            indexer -> metadb "status = CONVERTED"
            indexer -> temporal "Nhận activity index"
            indexer -> embed "Embed theo lô"
            indexer -> vectordb "Upsert, xóa version cũ"
            indexer -> metadb "status = INDEXED"
            autoLayout lr
        }

        component api "L3-IngestionAPI" "Level 3 - Component: Ingestion API" {
            include *
            autoLayout lr
        }

        component converter "L3-ConversionWorker" "Level 3 - Component: Conversion Worker" {
            include *
            autoLayout lr
        }

        component indexer "L3-IndexingWorker" "Level 3 - Component: Indexing Worker (workflow + index)" {
            include *
            autoLayout lr
        }

        styles {
            element "Person" {
                shape Person
                background #08427B
                color #ffffff
            }
            element "Software System" {
                background #1168BD
                color #ffffff
            }
            element "External" {
                background #8C8C8C
                color #ffffff
            }
            element "Container" {
                background #438DD5
                color #ffffff
            }
            element "Temporal" {
                background #5B3FA0
                color #ffffff
            }
            element "Component" {
                background #85BBF0
                color #000000
            }
            element "Module" {
                background #D6E9FB
                color #000000
            }
            element "Database" {
                shape Cylinder
            }
            element "WebBrowser" {
                shape WebBrowser
            }
        }
    }
}
