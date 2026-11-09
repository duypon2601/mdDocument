# Bí kíp Temporal: khái niệm và cách dùng

## 1. Temporal giải quyết vấn đề gì

Có những việc cần nhiều bước và chạy lâu: gọi API ngoài, gọi LLM, xử lý dữ liệu, ghi file.
Nếu viết thành một hàm bình thường thì sẽ gặp các vấn đề sau:
- Máy chết giữa chừng thì mất hết, phải chạy lại từ đầu.
- Một bước lỗi tạm thời (mạng chập chờn, API trả 429) thì cả job hỏng.
- Không biết job đang ở bước nào, cũng không có cách huỷ hay đặt timeout cho cả job.

Temporal **ghi lại lịch sử từng bước** của job. Máy chết thì worker khác nhận job và chạy tiếp
từ bước đang dở. Bước nào lỗi thì chỉ bước đó được retry theo chính sách mình đặt.

## 2. Năm khái niệm cần nắm

| Khái niệm | Là gì | Ví dụ đời thường |
|---|---|---|
| **Workflow** | Code điều phối: gọi bước nào, theo thứ tự nào, timeout và retry ra sao | Người quản lý phân việc |
| **Activity** | Một bước làm việc thật: gọi API, đọc/ghi DB, tính toán nặng | Nhân viên làm từng việc |
| **Worker** | Process chạy code workflow và activity, lấy việc từ task queue | Văn phòng có nhân viên |
| **Task queue** | Hàng đợi có tên, nối client với worker | Hộp thư nhận việc |
| **Client** | Code bên ngoài dùng để khởi động workflow, đọc trạng thái, lấy kết quả | Khách hàng gửi yêu cầu |

```text
Client ──start_workflow──► Temporal Server ──task queue──► Worker
                              (lưu lịch sử)                  ├─ chạy Workflow (điều phối)
Client ◄──kết quả / trạng thái──┘                            └─ chạy Activity (làm việc thật)
```

## 3. Một job chạy thế nào

1. Client gọi `start_workflow(...)`, truyền tên workflow, input, `id` của job và task queue.
2. Server ghi nhận job rồi đưa vào task queue.
3. Worker đang lắng nghe queue đó nhận job và chạy hàm `run` của workflow.
4. Mỗi lần workflow gọi `execute_activity(...)`, server xếp activity vào queue. Một worker
   (có thể là máy khác) chạy activity rồi trả kết quả về.
5. Server lưu kết quả của từng activity vào lịch sử.
6. Worker chết giữa chừng thì worker khác **replay** lịch sử: bước nào đã có kết quả thì không
   chạy lại, chỉ chạy tiếp từ chỗ dở.
7. Client lấy kết quả bằng `handle.result()`, hoặc xem trạng thái bằng `handle.describe()`.

## 4. Code mẫu (Python SDK `temporalio`)

**Payload**: input và output dùng `@dataclass`, field kiểu đơn giản.

```python
from dataclasses import dataclass, field

@dataclass
class OrderInput:
    order_id: str
    items: list[str]

@dataclass
class PriceResult:
    order_id: str
    total: float
    notes: list[str] = field(default_factory=list)   # field mới luôn có default
```

**Activity**: nơi làm I/O thật.

```python
from temporalio import activity
from temporalio.exceptions import ApplicationError

@activity.defn(name="price_order")
async def price_order(inp: OrderInput) -> PriceResult:
    if not inp.items:
        # Lỗi chạy lại vẫn hỏng thì đánh dấu non_retryable
        raise ApplicationError("Đơn hàng rỗng", type="EMPTY_ORDER", non_retryable=True)
    total = await call_pricing_api(inp.items)          # I/O nằm ở đây
    return PriceResult(order_id=inp.order_id, total=total)
```

**Workflow**: chỉ điều phối.

```python
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

@workflow.defn(name="OrderWorkflow")
class OrderWorkflow:
    def __init__(self) -> None:
        self._status = "Đang chờ"

    @workflow.query(name="get_progress")
    def get_progress(self) -> str:
        return self._status

    @workflow.run
    async def run(self, inp: OrderInput) -> PriceResult:
        self._status = "Đang tính giá"
        result = await workflow.execute_activity(
            "price_order", inp,
            result_type=PriceResult,                       # bắt buộc khi gọi bằng tên chuỗi
            start_to_close_timeout=timedelta(seconds=30),  # trần cho MỘT lần chạy
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=2),
                backoff_coefficient=2,
            ),
        )
        self._status = "Hoàn tất"
        return result
```

**Worker**: đăng ký workflow và activity vào một task queue.

```python
from temporalio.client import Client
from temporalio.worker import Worker

async def main():
    client = await Client.connect("localhost:7233")
    worker = Worker(
        client,
        task_queue="order-queue",
        workflows=[OrderWorkflow],
        activities=[price_order],      # quên đăng ký thì activity treo đến hết timeout
    )
    await worker.run()
```

**Client**: khởi động job, theo dõi và lấy kết quả.

```python
handle = await client.start_workflow(
    "OrderWorkflow",
    OrderInput(order_id="A1", items=["x", "y"]),
    id="order-A1",                                  # id duy nhất cho mỗi job
    task_queue="order-queue",
    execution_timeout=timedelta(minutes=5),         # trần của cả job
)
print(await handle.query("get_progress"))           # xem tiến độ khi đang chạy
result = await handle.result()                       # chờ kết quả
```

## 5. Luật bắt buộc

### Workflow phải deterministic

Khi replay, workflow chạy lại từ đầu và phải ra **đúng** chuỗi lệnh như lần trước. Vì vậy
trong workflow **không được**:
- Gọi API, đọc/ghi file hay DB: việc này đưa vào activity.
- Dùng `datetime.now()`, `time.time()`, `random`, `uuid4()`: dùng `workflow.now()`,
  `workflow.random()`, `workflow.uuid4()`.
- Dùng `time.sleep()` hay `asyncio.sleep()` thường: dùng `await asyncio.sleep()` bên trong
  workflow (SDK sẽ chuyển thành timer), hoặc `workflow.sleep()`.
- Sửa thứ tự hay tên activity của workflow khi đang có job chạy dở: lúc replay sẽ lỗi
  non-determinism. Cần đổi thì dùng versioning (`workflow.patched`).

### Activity phải idempotent

Activity có thể chạy **nhiều lần** (retry, hoặc worker chết sau khi làm xong nhưng chưa kịp
báo kết quả). Chạy lại cùng input phải ra cùng kết quả và không gây side effect lặp:
- Key ghi file hoặc DB sinh từ input (`f"orders/{order_id}/price.json"`), không sinh từ uuid
  hay thời gian.
- Ghi theo kiểu "chỉ ghi nếu chưa có". Nếu đã có thì đọc lại bản cũ.
- Bước tốn tiền (gọi LLM trả phí, gửi email) mà chưa idempotent thì đặt `maximum_attempts=1`.

### Payload nhỏ và tự chứa

- Input và output đi qua server và được lưu vào lịch sử, nên phải **nhỏ**. Mặc định nên dưới
  vài trăm KB. Dữ liệu lớn thì ghi lên storage (S3…) và chỉ truyền key.
- **Không truyền** giữa các bước: đường dẫn file local, kết nối DB, client, object trong RAM.
  Hai activity có thể chạy trên hai máy khác nhau.
- Thư mục tạm chỉ dùng trong một activity, xong activity thì coi như đã mất.
- Thêm field vào dataclass thì luôn đặt default, để job đang chạy dở với payload cũ vẫn đọc được.

### Không chờ trong activity

Không `sleep`, không viết vòng lặp poll để chờ trong activity. Việc chờ (timer, chờ signal)
là việc của workflow.

## 6. Timeout và retry

| Tham số | Ý nghĩa | Khi nào dùng |
|---|---|---|
| `start_to_close_timeout` | Trần cho **một lần** chạy activity | Luôn đặt |
| `schedule_to_close_timeout` | Trần cho **tất cả** các lần chạy, tính cả thời gian xếp hàng | Khi job có deadline tổng |
| `heartbeat_timeout` | Activity phải báo "còn sống" trong khoảng này, nếu không bị coi là chết | Activity chạy lâu (> 30s) |
| `execution_timeout` (khi start) | Trần của cả workflow | Luôn đặt cho job có giới hạn thời gian |
| `RetryPolicy` | Số lần thử, khoảng chờ, hệ số backoff | Tuỳ độ rủi ro của bước |

Lỗi nào không nên retry (input sai, thiếu quyền, dữ liệu không tồn tại) thì raise
`ApplicationError(..., non_retryable=True)`. Đặt `type` là một mã cố định dạng `UPPER_SNAKE`
để code phía trên rẽ nhánh theo mã, không phải theo câu thông báo.

**Activity chạy lâu** thì gửi heartbeat định kỳ. Khi bị huỷ, activity sẽ nhận được tín hiệu
qua lần heartbeat tiếp theo:

```python
@activity.defn
async def long_task(inp: TaskInput) -> TaskResult:
    for i, chunk in enumerate(inp.chunks):
        activity.heartbeat({"done": i})     # báo tiến độ, đồng thời là điểm nhận lệnh huỷ
        await process(chunk)
    return TaskResult(...)
```

## 7. Chia bước thế nào cho hợp lý

| Nên tách thành nhiều activity khi | Một activity là đủ khi |
|---|---|
| Có bước chậm hoặc dễ lỗi (API ngoài, LLM) cần retry riêng | Việc ngắn, rẻ, chạy lại từ đầu cũng không sao |
| Có bước tốn tiền, không muốn chạy lại khi bước sau hỏng | Chỉ là tính toán thuần |
| Job dài, chết giữa chừng mất nhiều công | |
| Cần chạy song song (fan-out theo danh sách) | |

Chạy song song nhiều activity trong workflow:

```python
results = await asyncio.gather(*[
    workflow.execute_activity("process_item", item, result_type=ItemResult,
                              start_to_close_timeout=timedelta(seconds=30))
    for item in items
])
```

Đừng chia bước chỉ cho có. Mỗi activity tốn thêm một vòng đi qua server và làm lịch sử dài thêm.

## 8. Query, Signal, Cancel

- **Query** (`@workflow.query`): đọc trạng thái hoặc tiến độ của workflow đang chạy. Chỉ đọc,
  không được đổi state.
- **Signal** (`@workflow.signal`): gửi dữ liệu vào workflow đang chạy, ví dụ "người dùng đã
  duyệt".
- **Cancel** (`handle.cancel()`): yêu cầu huỷ job. Activity đang chạy sẽ nhận lệnh huỷ qua
  heartbeat.

## 9. Test

- Logic nghiệp vụ nên tách thành hàm thuần, test bằng pytest bình thường, không cần Temporal.
- Test workflow bằng `temporalio.testing.WorkflowEnvironment` (có chế độ tua nhanh thời gian)
  và mock activity.
- Với mỗi activity, nên có ba test:
  - payload đi qua JSON không mất dữ liệu (roundtrip),
  - chạy lại cùng input ra cùng kết quả,
  - activity vẫn chạy đúng khi thư mục tạm bị xoá giữa các bước.

## 10. Lỗi hay gặp

| Triệu chứng | Nguyên nhân thường gặp |
|---|---|
| Activity trả về `dict` thay vì dataclass | Quên `result_type` khi gọi activity bằng tên chuỗi |
| Job treo, không chạy | Sai tên task queue, hoặc worker chưa đăng ký workflow/activity đó |
| Lỗi non-determinism sau khi deploy | Đổi code workflow khi còn job chạy dở, hoặc gọi I/O hay `datetime.now()` trong workflow |
| Bước sau không thấy file bước trước ghi | Truyền đường dẫn local giữa hai activity chạy trên hai máy |
| Retry làm ghi trùng dữ liệu | Key sinh từ uuid hoặc thời gian, activity không idempotent |
| Activity bị timeout dù vẫn đang chạy | Chạy lâu mà không gửi heartbeat, hoặc `start_to_close_timeout` quá ngắn |
| Payload quá lớn, job fail | Trả dữ liệu lớn thẳng trong output thay vì ghi storage rồi trả key |

## 11. Checklist khi viết một workflow mới

- [ ] Input và output là dataclass, field mới có default, kích thước nhỏ.
- [ ] Workflow không làm I/O, không dùng giờ, random hay uuid của hệ thống.
- [ ] Mỗi activity idempotent, key ghi dữ liệu sinh từ input.
- [ ] Mọi `execute_activity` đều có timeout và retry policy phù hợp.
- [ ] Lỗi không nên retry dùng `non_retryable=True` và có `type` cố định.
- [ ] Activity chạy lâu có heartbeat.
- [ ] Đã đăng ký đủ workflow và activity trong worker.
- [ ] Có test cho logic, test roundtrip payload và test chạy lại.

Tài liệu chính thức: https://docs.temporal.io (phần Python SDK).
 