workspace "RAG Starter System" "Kiến trúc hệ thống RAG Monorepo (Django + Next.js + Qdrant + Celery) của KashifAgha/rag-starter" {

    !impliedRelationships true

    model {
        // ---------- Người dùng (Actors) ----------
        user = person "Người dùng" "Đăng ký/đăng nhập tài khoản, tải lên tài liệu, tra cứu và hỏi đáp qua chat có trích dẫn nguồn"
        admin = person "Quản trị viên" "Quản lý dữ liệu qua Django Admin (/admin), kiểm tra probe sức khỏe (/api/health), theo dõi LLM trace"

        // ---------- Hệ thống bên ngoài (External Systems) ----------
        llmProvider = softwareSystem "LLM / VLM Provider" "Cung cấp model sinh câu trả lời, nhận diện ngôn ngữ, rephrase câu hỏi và tóm tắt trang (OpenAI, Azure, OpenRouter, vLLM hoặc Ollama)" "External"
        embedProvider = softwareSystem "Embedding Provider" "Tạo vector nhúng ngữ nghĩa (OpenAI text-embedding-3-small, FastEmbed, hoặc Ollama nomic-embed-text)" "External"
        remoteSources = softwareSystem "Nguồn tài liệu từ xa" "Trích xuất nội dung từ Website (sitemap XML) hoặc không gian Atlassian Confluence" "External"
        langfuse = softwareSystem "Langfuse Observability" "Thu thập trace LLM, đo lường chi phí, token usage và đánh giá chất lượng prompt" "External"

        // ---------- Hệ thống RAG Starter ----------
        ragSystem = softwareSystem "RAG Starter System" "Hệ thống RAG mã nguồn mở monorepo (Django + Next.js), xử lý ingestion đa định dạng và hỏi đáp thông minh có trích dẫn nguồn" {

            webApp = container "Web Application" "Giao diện chat trực tuyến, quản lý upload tài liệu, hiển thị trích dẫn nguồn và SSE streaming" "Next.js 16, React 19, TypeScript, Tailwind CSS" "WebBrowser"

            backendApi = container "Backend API Service" "Cung cấp REST API, xác thực JWT, điều phối LangGraph, stream SSE và quản lý CRUD tài liệu" "Python 3.13, Django 5.1, DRF, Gunicorn, LangChain, LangGraph" "Container" {
                authCtl = component "Auth & Token Controller" "Đăng ký tài khoản, đăng nhập, phát hành và làm mới JWT token" "Django REST Framework, SimpleJWT"
                healthCtl = component "Health Check Controller" "Kiểm tra tình trạng kết nối DB, Redis, Qdrant, MinIO (/api/health/)" "Django View"
                docCtl = component "Document ViewSet" "Upload file, upload hàng loạt, nạp từ URL/sitemap/Confluence, re-index, sinh download URL" "Django REST Framework ViewSet"
                chatCtl = component "Chat ViewSet & SSE Streamer" "Nhận câu hỏi, kiểm tra giới hạn tốc độ (rate limit), stream token và trích dẫn qua SSE (/api/chat/ask/)" "Django View, StreamingHttpResponse"
                chatGraph = component "LangGraph Chat Graph Engine" "Đồ thị xử lý hội thoại: xác định ngôn ngữ → viết lại câu hỏi → truy vấn ngữ cảnh → sinh câu trả lời" "LangGraph, LangChain"
                retriever = component "Composite Retriever" "Truy vấn đồng thời đa dạng nội dung (text, table, image, summary), mở rộng summary hits, deduplicate và lọc ngưỡng" "LangChain Qdrant Retriever"
                reranker = component "FlashRank Reranker" "Xếp hạng lại các đoạn văn bản bằng Cross-Encoder (FlashRank ONNX CPU) trước khi gửi cho LLM" "FlashRank ONNX"
                llmAdapter = component "LLM Adapter" "Đóng gói kết nối và gọi model ngôn ngữ với OpenAI-compatible API" "LangChain ChatOpenAI"
                ormModels = component "ORM Models & Repositories" "Quản lý Document, Chunk, Conversation, Message và tenant isolation" "Django ORM"
            }

            celeryWorker = container "Ingestion Worker" "Thực thi trích xuất file (Docling/MarkItDown), chunking, tóm tắt trang qua LLM, sinh embedding và upsert vào Vector DB" "Python 3.13, Celery (concurrency=1), Docling, MarkItDown, pypdf" "Container" {
                taskRunner = component "Celery Task Runner" "Thực thi tác vụ ingest_document_task & enrich_document_task, bảo vệ chống OOM lặp lại bằng Redis attempts tracking" "Celery shared_task"
                securityValidator = component "Security & Upload Validator" "Kiểm tra MIME magic-byte, chặn path traversal, chặn SSRF khi tải URL/sitemap từ xa" "python-magic, ipaddress"
                remoteExtractor = component "Remote Source Extractor" "Cào dữ liệu web từ URL/sitemap (Trafilatura) hoặc đọc không gian tài liệu Confluence" "Trafilatura, Confluence REST Client"
                extractChain = component "Document Extraction Chain" "Chuỗi giải nén tài liệu theo thứ tự ưu tiên: Docling (OCR/bảng) → MarkItDown → pypdf → Plain text" "Docling, MarkItDown, pypdf"
                chunkingService = component "Chunking Service" "Cắt Markdown theo cấu trúc heading, giữ nguyên vẹn bảng biểu, tính content hash sha256" "LangChain Splitter"
                enricherService = component "Page Summarizer & Captioner" "Tóm tắt từng trang bằng LLM (SUMMARY chunk) và chú thích ảnh bằng VLM (IMAGE chunk)" "LangChain LLM, VLM"
                vectorIndexer = component "Vector Indexer & Store Client" "Sinh dense vector & BM25 sparse vector, upsert idempotent vào Qdrant theo tenant owner_id" "qdrant-client, fastembed"
                storageClient = component "Object Storage Client" "Lưu và đọc file tài liệu gốc vào MinIO bucket" "Boto3 / MinIO SDK"
            }

            celeryBeat = container "Celery Beat Scheduler" "Định kỳ quét và dọn dẹp các tài liệu bị kẹt ở trạng thái PROCESSING (reap_stuck_documents)" "Python 3.13, Celery Beat" "Container"

            postgresDb = container "Relational Database" "Lưu trữ tài khoản người dùng, metadata tài liệu, chunks, lịch sử hội thoại và tin nhắn chat" "PostgreSQL 17" "Database"

            redisBroker = container "Message Broker & Cache" "Hàng đợi tác vụ Celery, bộ đếm số lần worker lost và cache chia sẻ" "Redis 7" "Database"

            minioStorage = container "Object Storage" "Lưu trữ file tài liệu gốc tải lên, phục vụ tải về và đối chiếu trích dẫn nguồn" "MinIO (S3 compatible)" "Database"

            qdrantDb = container "Vector Database" "Lưu trữ hybrid vectors (dense + BM25 sparse) và payload, phân vùng dữ liệu theo tenant (owner_id)" "Qdrant 1.12" "Database"

            ollamaLocal = container "Local LLM Server (Tùy chọn)" "Chạy model LLM và Embedding offline trên máy chủ khi bật profile local-llm" "Ollama" "Container"
        }

        // ---------- Quan hệ Level 1 (System Context) ----------
        user -> ragSystem "Upload tài liệu, trò chuyện tra cứu, xem trích dẫn nguồn" "HTTPS"
        admin -> ragSystem "Quản trị dữ liệu qua Django admin, kiểm tra health probe" "HTTPS"
        ragSystem -> llmProvider "Gửi prompt chat, rephrase câu hỏi, tóm tắt trang, caption ảnh" "HTTPS / REST"
        ragSystem -> embedProvider "Tạo dense vector embeddings" "HTTPS / REST"
        ragSystem -> remoteSources "Tải trang web, sitemap XML, bài viết Confluence" "HTTPS / REST"
        ragSystem -> langfuse "Gửi telemetry trace, token usage và cost" "HTTPS / OTLP"

        // ---------- Quan hệ Level 2 (Container) ----------
        user -> webApp "Truy cập giao diện web, chat, upload file" "HTTPS"
        admin -> webApp "Đăng nhập giao diện web" "HTTPS"
        admin -> backendApi "Quản trị qua /admin/, kiểm tra /api/health/" "HTTPS"
        webApp -> backendApi "Gọi REST API, stream SSE /api/chat/ask/" "HTTPS / JWT"

        backendApi -> postgresDb "Lưu/đọc users, documents, chunks, chat history" "SQL (TCP 5432)"
        backendApi -> redisBroker "Đẩy tác vụ ingest vào queue, đọc/ghi cache" "Redis protocol (TCP 6379)"
        backendApi -> minioStorage "Lưu file upload ban đầu, tạo presigned URL tải file" "S3 API (TCP 9000)"
        backendApi -> qdrantDb "Truy vấn hybrid search (dense + BM25 sparse) kèm filter owner_id" "HTTP/gRPC (TCP 6333)"
        backendApi -> llmProvider "Gọi LLM suy luận, rephrase, generate câu trả lời" "HTTPS / REST"
        backendApi -> embedProvider "Tạo embedding câu hỏi" "HTTPS / REST"
        backendApi -> langfuse "Gửi trace LangChain & LangGraph" "HTTPS"
        backendApi -> ollamaLocal "Gọi model offline khi chạy local-llm profile" "HTTP (TCP 11434)"

        celeryWorker -> redisBroker "Lắng nghe nhận task ingest/enrich, kiểm tra worker-loss count" "Redis protocol"
        celeryWorker -> postgresDb "Cập nhật trạng thái UPLOADING → PROCESSING → READY | ERROR, lưu metadata chunks" "SQL"
        celeryWorker -> minioStorage "Đọc file gốc để trích xuất văn bản" "S3 API"
        celeryWorker -> qdrantDb "Upsert hybrid vectors và chunk payload kèm owner_id" "HTTP/gRPC"
        celeryWorker -> remoteSources "Cào website, tải sitemap, gọi Confluence API" "HTTPS"
        celeryWorker -> llmProvider "Gọi LLM tóm tắt từng trang và VLM chú thích ảnh" "HTTPS / REST"
        celeryWorker -> embedProvider "Tạo dense embedding cho từng chunk" "HTTPS / REST"
        celeryWorker -> ollamaLocal "Tạo embedding và LLM summary offline khi chạy local-llm profile" "HTTP (TCP 11434)"

        celeryBeat -> redisBroker "Đẩy tác vụ định kỳ reap_stuck_documents" "Redis protocol"

        // ---------- Quan hệ Level 3 (Backend API Components) ----------
        webApp -> authCtl "Đăng ký, lấy và làm mới JWT token" "POST /api/token/"
        webApp -> docCtl "Upload file, xem danh sách tài liệu, re-index" "REST"
        webApp -> chatCtl "Gửi câu hỏi, nhận SSE stream token & citations" "POST /api/chat/ask/"

        docCtl -> ormModels "Tạo Document record, gán owner_id" "ORM"
        docCtl -> minioStorage "Lưu file upload vào S3 bucket" "S3 API"
        docCtl -> redisBroker "Gọi delay() đẩy task ingest_document_task" "Celery"

        chatCtl -> ormModels "Lưu Conversation và Message" "ORM"
        chatCtl -> chatGraph "Khởi chạy đồ thị LangGraph với câu hỏi và lịch sử chat" "In-process call"
        chatGraph -> llmAdapter "Xác định ngôn ngữ và rephrase câu hỏi" "LangChain"
        chatGraph -> retriever "Truy vấn các chunk liên quan theo từng content type" "In-process call"
        retriever -> qdrantDb "Hybrid search: dense + sparse vectors với filter owner_id" "gRPC/HTTP"
        retriever -> reranker "Gửi danh sách ứng viên chunk để rerank" "In-process call"
        chatGraph -> llmAdapter "Sinh câu trả lời từ ngữ cảnh đã rerank" "LangChain"
        llmAdapter -> llmProvider "Gọi API chat completion" "HTTPS"

        healthCtl -> postgresDb "Kiểm tra kết nối PostgreSQL" "SQL"
        healthCtl -> redisBroker "Kiểm tra kết nối Redis" "PING"
        healthCtl -> qdrantDb "Kiểm tra collection vector" "HTTP GET"
        healthCtl -> minioStorage "Kiểm tra S3 bucket" "S3 API"

        // ---------- Quan hệ Level 3 (Celery Ingestion Worker Components) ----------
        redisBroker -> taskRunner "Nhận task ingest_document_task(doc_id)" "Celery"
        taskRunner -> redisBroker "Tăng bộ đếm worker loss attempts (chặn lặp OOM)" "Redis INCR"
        taskRunner -> ormModels "Cập nhật Document status sang PROCESSING" "ORM"
        taskRunner -> storageClient "Đọc file gốc từ MinIO" "S3 API"
        storageClient -> minioStorage "Đọc/ghi bucket S3" "S3 API"
        taskRunner -> securityValidator "Kiểm tra định dạng file thực và bảo vệ SSRF" "In-process call"
        taskRunner -> remoteExtractor "Trích xuất nội dung URL/sitemap/Confluence" "In-process call"
        remoteExtractor -> remoteSources "Tải dữ liệu từ xa" "HTTPS"
        taskRunner -> extractChain "Trích xuất tài liệu sang Markdown (Docling → MarkItDown → pypdf)" "In-process call"
        taskRunner -> chunkingService "Chia nhỏ Markdown theo heading, giữ bảng biểu nguyên vẹn" "In-process call"
        taskRunner -> enricherService "Tạo page summaries (LLM) và captions ảnh (VLM)" "In-process call"
        enricherService -> llmProvider "Gọi LLM/VLM tạo summary và caption" "HTTPS"
        taskRunner -> vectorIndexer "Tạo embeddings (dense + sparse) và upsert vào Qdrant" "In-process call"
        vectorIndexer -> embedProvider "Gọi API sinh dense vectors" "HTTPS"
        vectorIndexer -> qdrantDb "Upsert points với ID = hash nội dung (idempotent)" "gRPC/HTTP"
        taskRunner -> ormModels "Lưu Chunk records vào Postgres, đổi status sang READY" "ORM"
    }

    views {
        properties {
            "c4plantuml.tags" "true"
        }

        systemContext ragSystem "L1-SystemContext" "Level 1 - System Context: RAG Starter System" {
            include *
            autoLayout lr
        }

        container ragSystem "L2-Container" "Level 2 - Container: RAG Starter System" {
            include *
            autoLayout lr
        }

        dynamic ragSystem "L2-Flow-Ingestion" "Luồng xử lý nạp và trích xuất tài liệu (Document Ingestion Flow)" {
            user -> webApp "Tải lên file tài liệu (PDF, DOCX, XLSX...)"
            webApp -> backendApi "POST /api/documents/ (multipart/form-data)"
            backendApi -> minioStorage "Lưu file gốc vào S3 bucket"
            backendApi -> postgresDb "Tạo Document (status=UPLOADING) với owner_id"
            backendApi -> redisBroker "Đẩy task ingest_document_task vào queue"
            celeryWorker -> redisBroker "Nhận task ingest_document_task"
            celeryWorker -> postgresDb "Cập nhật status = PROCESSING"
            celeryWorker -> minioStorage "Đọc file gốc từ S3 bucket"
            celeryWorker -> llmProvider "Gọi LLM tóm tắt từng trang và VLM caption ảnh (nếu bật)"
            celeryWorker -> embedProvider "Tạo dense vector embeddings"
            celeryWorker -> qdrantDb "Upsert hybrid vectors và chunk payload kèm owner_id"
            celeryWorker -> postgresDb "Lưu metadata chunks, cập nhật status = READY"
            autoLayout lr
        }

        dynamic ragSystem "L2-Flow-Chat" "Luồng hỏi đáp RAG và stream câu trả lời kèm trích dẫn (Chat & QA Flow)" {
            user -> webApp "Gửi câu hỏi trong phiên hội thoại"
            webApp -> backendApi "POST /api/chat/ask/ (SSE stream request)"
            backendApi -> llmProvider "Xác định ngôn ngữ và rephrase câu hỏi dựa trên lịch sử"
            backendApi -> qdrantDb "Tìm kiếm hybrid dense + sparse (lọc theo owner_id)"
            backendApi -> webApp "Phát tín hiệu trích dẫn citations qua SSE trước"
            backendApi -> llmProvider "Sinh câu trả lời từ ngữ cảnh đã rerank"
            backendApi -> webApp "Stream từng token câu trả lời về giao diện người dùng theo thời gian thực"
            backendApi -> postgresDb "Lưu câu hỏi và câu trả lời vào Message history"
            autoLayout lr
        }

        component backendApi "L3-BackendAPI" "Level 3 - Component: Backend API Service (Django REST Framework)" {
            include *
            autoLayout lr
        }

        component celeryWorker "L3-IngestionWorker" "Level 3 - Component: Ingestion Worker (Celery)" {
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
            element "Component" {
                background #85BBF0
                color #000000
            }
            element "Database" {
                shape Cylinder
                background #2A6F97
                color #ffffff
            }
            element "WebBrowser" {
                shape WebBrowser
                background #014F86
                color #ffffff
            }
        }
    }
}
