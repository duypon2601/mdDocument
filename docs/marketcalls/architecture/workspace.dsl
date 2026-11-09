workspace "OpenRAG Platform" "Kiến trúc hệ thống OpenRAG (FastAPI + React + Celery + Qdrant + LiteLLM + TEI) của marketcalls/openrag" {

    !impliedRelationships true

    model {
        // ---------- Người dùng (Actors) ----------
        user = person "Người dùng" "Đăng nhập tài khoản, quản lý tài liệu trong workspace, tra cứu tri thức qua chat, nhận câu trả lời có trích dẫn nguồn và biểu đồ phân tích"
        admin = person "Quản trị viên" "Quản lý tổ chức, phân quyền RBAC, đăng ký mô hình LLM, giám sát hạn ngạch token và đánh giá chất lượng RAG"

        // ---------- Hệ thống bên ngoài (External Systems) ----------
        llmProvider = softwareSystem "LLM / VLM Provider" "Cung cấp mô hình ngôn ngữ lớn (OpenAI GPT-5.6, Azure OpenAI, Anthropic, Bedrock, vLLM, Ollama) qua thư viện LiteLLM nhúng trong tiến trình" "External"
        embedProvider = softwareSystem "Embedding Provider" "Cung cấp mô hình nhúng vector ngữ nghĩa (Text Embeddings Inference TEI nội bộ hoặc nhà cung cấp hosted qua LiteLLM)" "External"
        remoteSources = softwareSystem "Nguồn dữ liệu ngoài" "Kết nối đồng bộ tài liệu từ lưu trữ đám mây, ổ đĩa chia sẻ hoặc trang web" "External"
        observability = softwareSystem "Observability Platform" "Hạ tầng giám sát OpenTelemetry thu thập traces, metrics và logs (Prometheus, Grafana, Loki, Tempo)" "External"

        // ---------- Hệ thống OpenRAG Platform ----------
        openragSystem = softwareSystem "OpenRAG Platform" "Hệ thống AI Assistant doanh nghiệp mã nguồn mở, tự host, hỗ trợ truy xuất tri thức có bằng chứng xác minh, phân quyền đa tầng và kiểm soát mô hình nghiêm ngặt" {

            webApp = container "Web Application" "Giao diện người dùng: chat trực tiếp qua SSE, hiển thị trích dẫn bằng chứng, quản lý duyệt tài liệu và trực quan hóa bảng biểu phân tích" "React 18, TypeScript, Tailwind CSS, Vite, Nginx" "WebBrowser"

            apiService = container "Backend API Service" "Cung cấp REST & SSE API, xác thực JWT/MFA, phân quyền RBAC, điều phối Agentic RAG qua Agno, kiểm dịch upload và điều hướng sự kiện" "Python 3.12, FastAPI, SQLAlchemy (asyncpg), LiteLLM, Agno" "Container" {
                authCtl = component "Auth & RBAC Controller" "Đăng nhập, cấp JWT, quản lý phiên làm việc, lời mời thành viên và phân quyền vai trò (Superadmin, Org Admin, Workspace Member)" "FastAPI Router, Pydantic, Passlib"
                docCtl = component "Document & Quarantine Controller" "Xử lý tải file vào vùng cách ly kiểm duyệt, phê duyệt nạp, tra cứu trạng thái và xóa tài liệu" "FastAPI Router"
                chatCtl = component "Chat & SSE Streaming Controller" "Tiếp nhận câu hỏi, mở luồng Server-Sent Events (SSE) phát token, trích dẫn bằng chứng và trạng thái thời gian thực" "FastAPI Router, Starlette StreamingResponse"
                agnoEngine = component "Agno Agentic Orchestrator" "Điều phối vòng lặp tác tử (agent loop) tự động lập kế hoạch truy vấn, giới hạn tối đa 4 lượt gọi công cụ đọc an toàn (bounded read-only tools)" "Agno Framework, Python"
                retriever = component "Hybrid Retrieval Engine" "Tìm kiếm kết hợp dense vector và sparse BM25 trên Qdrant, áp bộ lọc tenant cứng, lấy chunk lân cận và xếp hạng lại" "Python, Qdrant Client"
                groundingVal = component "Evidence & Grounding Validator" "Đối chiếu bằng chứng truy xuất trong PostgreSQL, kiểm tra tính xác thực của số trang/tiêu đề và từ chối nếu thiếu căn cứ" "Python Domain Logic"
                artifactGen = component "Analytics Artifact Engine" "Sinh bổ sung biểu đồ Vega-Lite và bảng dữ liệu an toàn theo hợp đồng analytics.v1 khi câu hỏi yêu cầu phân tích số liệu" "Python Schema, Vega-Lite"
                modelGateway = component "Model Gateway & Prober" "Đóng gói thư viện LiteLLM, quản lý danh mục mô hình, thực hiện probe kiểm tra năng lực (streaming, structured output, vision, tools)" "LiteLLM in-process, Pydantic"
                secretVault = component "Envelope Encryption Vault" "Mã hóa khóa API nhà cung cấp bằng cơ chế envelope encryption (Master KEK file + DEK per secret)" "Cryptography Fernet/AES-GCM"
                outboxDispatcher = component "Transactional Outbox Dispatcher" "Ghi nhận sự kiện vào bảng outbox và đẩy vào Redis Streams đồng bộ với transaction cơ sở dữ liệu" "SQLAlchemy asyncpg"
            }

            celeryWorker = container "Celery Worker Fleet" "Cụm worker nền đa hàng đợi: xử lý trích xuất Docling/OCR, chia chunk, sinh embedding, đánh giá golden dataset và thăm dò model" "Python 3.12, Celery, Docling, RapidOCR, LiteLLM" "Container" {
                taskRunner = component "Celery Task Runner" "Tiếp nhận và điều phối tác vụ từ các hàng đợi chuyên biệt (ingestion, runs, models, evaluations...)" "Celery Task Runner"
                docParser = component "Document Parser & OCR Pipeline" "Trích xuất văn bản bằng Docling, chạy RapidOCR cho trang scan/ảnh, fallback pypdfium2 cho PDF dung lượng lớn" "Docling, RapidOCR, pypdfium2"
                chunker = component "Semantic Chunking Engine" "Cắt nhỏ Markdown bảo toàn cấu trúc tiêu đề, bảo vệ khối bảng biểu, gắn nhãn EvidenceSpan và tính mã băm SHA-256" "Python Semantic Splitter"
                embedWorker = component "Embedding & Indexing Client" "Gọi TEI hoặc LiteLLM sinh vector, đẩy điểm vector kèm metadata chi tiết vào Qdrant" "tei-client, Qdrant Python Client"
                probeWorker = component "Model Capability Tester" "Kiểm tra thực tế các khả năng sinh văn bản, stream, gọi hàm và sinh JSON của mô hình mới đăng ký" "LiteLLM Async Probe"
                evalEngine = component "Evaluation & Benchmark Engine" "Chạy bộ đánh giá tự động dựa trên golden dataset, so sánh Simple RAG với Agentic RAG và xuất báo cáo đo lường" "Python Evaluation Suite"
            }

            celeryBeat = container "Celery Beat Scheduler" "Bộ lập lịch tác vụ định kỳ: điều phối quét tác vụ đến hạn, dọn tài liệu kẹt và kích hoạt backfill làm giàu dữ liệu" "Python 3.12, Celery Beat" "Container"

            eventWorker = container "Event Worker" "Tiến trình tiêu thụ sự kiện bền vững từ Redis Streams, đảm bảo mẫu Transactional Outbox xử lý tin cậy và không mất dữ liệu" "Python 3.12, Celery / Async Worker, Redis Streams" "Container"

            postgresDb = container "Relational Database" "Lưu trữ metadata tài liệu, tổ chức, workspace, tài khoản người dùng, bảng phân quyền RBAC, phiên chat, bằng chứng trích dẫn và khóa mã hóa" "PostgreSQL 16 Alpine" "Database"

            redisCache = container "Message Broker & Cache" "Hàng đợi tác vụ Celery (default, interactive, ingestion, models...), cache phiên và bộ đếm giới hạn tốc độ" "Redis 7 Alpine" "Database"

            eventRedis = container "Transactional Event Store" "Lưu trữ luồng sự kiện bền vững qua Redis Streams với cơ chế append-only file (AOF always)" "Redis 7.4 Alpine (Streams, AOF always)" "Database"

            minioStorage = container "Object Storage" "Lưu trữ tài liệu gốc, vùng cách ly kiểm duyệt file (quarantine), và dữ liệu xuất báo cáo" "MinIO (S3 compatible)" "Database"

            qdrantDb = container "Vector Database" "Lưu trữ vector dense và sparse BM25, hỗ trợ tìm kiếm kết hợp (hybrid search) với bộ lọc cứng cô lập tenant theo org_id và workspace_id" "Qdrant Vector DB" "Database"

            teiService = container "Text Embeddings Inference (TEI)" "Container HuggingFace TEI phục vụ sinh vector nhúng cục bộ tốc độ cao cho mô hình BGE-M3 / hash" "HuggingFace TEI / Docker" "Container"

            ollamaLocal = container "Local LLM Server (Tùy chọn)" "Chạy model LLM và embedding offline hoàn toàn trên máy chủ khi không kết nối API đám mây" "Ollama" "Container"
        }

        // ---------- Quan hệ Level 1 (System Context) ----------
        user -> openragSystem "Upload tài liệu, trò chuyện tra cứu có trích dẫn nguồn, khám phá biểu đồ phân tích" "HTTPS"
        admin -> openragSystem "Quản trị người dùng/workspace, phân quyền RBAC, cấu hình mô hình LLM, giám sát hạn ngạch" "HTTPS"
        openragSystem -> llmProvider "Gửi prompt chat, lập kế hoạch tác tử, stream câu trả lời, sinh biểu đồ phân tích" "HTTPS / REST"
        openragSystem -> embedProvider "Sinh vector nhúng ngữ nghĩa (dense / sparse) cho đoạn văn bản" "HTTP / gRPC"
        openragSystem -> remoteSources "Đồng bộ tài liệu định kỳ từ kho lưu trữ bên ngoài" "HTTPS / S3 API"
        openragSystem -> observability "Xuất traces, metrics và logs hiệu năng qua OpenTelemetry" "gRPC / OTLP"

        // ---------- Quan hệ Level 2 (Container) ----------
        user -> webApp "Tương tác giao diện người dùng, upload tài liệu, đặt câu hỏi chat" "HTTPS"
        admin -> webApp "Cấu hình hệ thống, quản lý tài liệu và mô hình" "HTTPS"
        webApp -> apiService "Gửi request REST API và duy trì kết nối SSE nhận streaming" "JSON / SSE over HTTPS"

        apiService -> postgresDb "Đọc/ghi metadata, users, workspaces, sessions, bằng chứng và outbox" "asyncpg / TCP 5432"
        apiService -> redisCache "Đẩy tác vụ vào hàng đợi Celery, kiểm tra rate limit" "Redis Protocol / TCP 6379"
        apiService -> eventRedis "Ghi nhận sự kiện nghiệp vụ vào Redis Streams outbox" "Redis RESP / TCP 6379"
        apiService -> minioStorage "Lưu file vào vùng cách ly (quarantine), tải file đã duyệt" "S3 API / HTTP 9000"
        apiService -> qdrantDb "Truy vấn hybrid search (dense + BM25) với bộ lọc tenant cứng" "HTTP / REST 6333"
        apiService -> teiService "Sinh vector embedding câu truy vấn tức thì" "HTTP 80"
        apiService -> llmProvider "Gọi mô hình sinh câu trả lời, lập kế hoạch Agno qua LiteLLM" "HTTPS"

        celeryWorker -> redisCache "Nhận tác vụ Celery từ hàng đợi ingestion, models, evaluations" "Redis Protocol"
        celeryWorker -> postgresDb "Cập nhật trạng thái tài liệu, ghi nhận kết quả đánh giá, chunk metadata" "asyncpg"
        celeryWorker -> minioStorage "Đọc file từ vùng cách ly, lưu file đã xử lý" "S3 API"
        celeryWorker -> teiService "Sinh vector embedding hàng loạt cho các chunk" "HTTP"
        celeryWorker -> qdrantDb "Upsert điểm vector kèm payload ngữ cảnh và bằng chứng" "HTTP / gRPC"
        celeryWorker -> llmProvider "Chạy probe kiểm tra năng lực mô hình, đánh giá benchmark" "HTTPS"

        celeryBeat -> redisCache "Lập lịch định kỳ đẩy tác vụ dọn dẹp, kiểm tra vào hàng đợi" "Redis Protocol"
        eventWorker -> eventRedis "Đọc sự kiện từ Redis Streams consumer group" "Redis RESP"
        eventWorker -> postgresDb "Cập nhật trạng thái vòng đời sự kiện idempotent" "asyncpg"

        apiService -> observability "Gửi OpenTelemetry traces và metrics" "OTLP / gRPC"
        celeryWorker -> observability "Gửi OpenTelemetry traces quá trình nạp và đánh giá" "OTLP / gRPC"

        // ---------- Quan hệ Level 3 - Backend API Components ----------
        webApp -> authCtl "Gửi thông tin đăng nhập, refresh token" "HTTPS / REST"
        webApp -> docCtl "Upload file lên vùng cách ly, gửi yêu cầu duyệt/xóa" "HTTPS / REST"
        webApp -> chatCtl "Gửi câu hỏi, mở kết nối nhận luồng SSE" "HTTPS / SSE"

        chatCtl -> agnoEngine "Khởi tạo vòng lặp tác tử, điều phối truy vấn"
        agnoEngine -> retriever "Yêu cầu tìm kiếm kết hợp (hybrid retrieval) với bộ lọc cứng"
        agnoEngine -> modelGateway "Gọi mô hình lập kế hoạch và sinh câu trả lời"
        retriever -> qdrantDb "Thực thi tìm kiếm vector dense + sparse"
        retriever -> teiService "Embed câu hỏi truy vấn"
        retriever -> postgresDb "Lấy chunk lân cận, nạp thông tin tài liệu"

        agnoEngine -> groundingVal "Xác minh bằng chứng và nguồn trích dẫn"
        groundingVal -> postgresDb "Kiểm tra tính hợp lệ của PageBlock và Document Version"
        chatCtl -> artifactGen "Sinh biểu đồ và bảng phân tích khi có yêu cầu analytics.v1"
        chatCtl -> postgresDb "Lưu phiên hội thoại và tin nhắn"

        docCtl -> minioStorage "Lưu file vào thư mục quarantine"
        docCtl -> postgresDb "Tạo bản ghi tài liệu trạng thái PENDING_APPROVAL"
        docCtl -> outboxDispatcher "Phát sinh sự kiện nạp tài liệu"
        outboxDispatcher -> postgresDb "Ghi sự kiện vào bảng outbox"
        outboxDispatcher -> eventRedis "Đẩy sự kiện vào Redis Stream"

        modelGateway -> secretVault "Giải mã API key của nhà cung cấp"
        secretVault -> postgresDb "Đọc bản ghi key đã mã hóa phong bì"
        modelGateway -> llmProvider "Gọi API mô hình qua LiteLLM"

        // ---------- Quan hệ Level 3 - Worker Fleet Components ----------
        redisCache -> taskRunner "Phân phối tác vụ Celery"
        taskRunner -> docParser "Thực thi trích xuất tài liệu (Docling / RapidOCR)"
        docParser -> minioStorage "Đọc file gốc từ quarantine"
        docParser -> chunker "Chuyển giao các PageBlock đã trích xuất"
        chunker -> embedWorker "Chuyển giao danh sách chunk kèm EvidenceSpan"
        embedWorker -> teiService "Sinh batch embedding"
        embedWorker -> qdrantDb "Upsert points vào collection Qdrant"
        embedWorker -> postgresDb "Ghi nhận chunk metadata và đổi trạng thái tài liệu sang INDEXED"

        taskRunner -> probeWorker "Thực thi tác vụ probe kiểm tra mô hình"
        probeWorker -> modelGateway "Gọi LiteLLM thăm dò năng lực"
        taskRunner -> evalEngine "Thực thi tác vụ benchmark golden dataset"
        evalEngine -> retriever "Truy xuất đối chiếu Simple RAG vs Agentic RAG"
        evalEngine -> postgresDb "Lưu kết quả đo lường và so sánh"
    }

    views {
        properties {
            "c4plantuml.tags" "true"
        }

        systemContext openragSystem "L1-SystemContext" "Level 1 - System Context: OpenRAG Platform" {
            include *
            autoLayout lr
        }

        container openragSystem "L2-Container" "Level 2 - Container: Kiến trúc container OpenRAG" {
            include *
            autoLayout lr
        }

        dynamic openragSystem "L2-Flow-Ingestion" "Luồng nạp tài liệu, kiểm dịch OCR và phê duyệt" {
            user -> webApp "1. Tải tài liệu lên giao diện"
            webApp -> apiService "2. Gửi file (POST /api/documents/)"
            apiService -> minioStorage "3. Lưu file vào vùng cách ly (quarantine)"
            apiService -> postgresDb "4. Tạo bản ghi PENDING_APPROVAL"
            user -> webApp "5. Xem trước và nhấn Duyệt (Approve)"
            webApp -> apiService "6. Gửi lệnh duyệt (POST /api/documents/{id}/approve)"
            apiService -> redisCache "7. Đẩy tác vụ ingest_document vào hàng đợi Celery"
            celeryWorker -> redisCache "8. Nhận tác vụ từ hàng đợi ingestion"
            celeryWorker -> minioStorage "9. Đọc file từ vùng cách ly"
            celeryWorker -> teiService "10. Sinh embedding cho các chunk"
            celeryWorker -> qdrantDb "11. Upsert vector và payload"
            celeryWorker -> postgresDb "12. Cập nhật trạng thái INDEXED"
            autoLayout lr
        }

        dynamic openragSystem "L2-Flow-Chat" "Luồng hỏi đáp Agentic RAG, xác minh bằng chứng và sinh biểu đồ" {
            user -> webApp "1. Đặt câu hỏi trong workspace"
            webApp -> apiService "2. Mở kết nối SSE (POST /api/chats/ask)"
            apiService -> llmProvider "3. Agno lập kế hoạch truy vấn qua LiteLLM"
            apiService -> qdrantDb "4. Tìm kiếm hybrid (dense + sparse) với bộ lọc tenant cứng"
            apiService -> postgresDb "5. Đối chiếu bằng chứng EvidenceSpan và số trang"
            apiService -> llmProvider "6. Sinh câu trả lời bám sát ngữ cảnh kèm trích dẫn"
            apiService -> webApp "7. Stream token câu trả lời và trích dẫn về giao diện"
            apiService -> llmProvider "8. Gọi bổ sung structured output sinh analytics.v1 (nếu cần)"
            apiService -> webApp "9. Gửi biểu đồ Vega-Lite / bảng dữ liệu an toàn"
            apiService -> postgresDb "10. Lưu phiên chat và tin nhắn"
            autoLayout lr
        }

        component apiService "L3-BackendAPI" "Level 3 - Component: Backend API Service" {
            include *
            autoLayout lr
        }

        component celeryWorker "L3-WorkerFleet" "Level 3 - Component: Celery Worker Fleet" {
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
            }
            element "WebBrowser" {
                shape WebBrowser
            }
        }
    }
}
