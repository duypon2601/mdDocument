# Viết workflow và activity với Temporal (Python)

Hướng dẫn này đi qua một ví dụ nhỏ giống luồng của dự án: đếm trang, đọc các lô trang song song, chờ người duyệt nếu đọc kém, rồi ghép kết quả. Mỗi bước kèm quy tắc cần nhớ và chỗ tương ứng trong code thật.

Code mẫu nằm ở [phụ lục](#phụ-lục-code-mẫu) cuối tài liệu. Chép từng file vào một thư mục `hoc/` đặt trong repo, thêm một file `__init__.py` rỗng. Code chạy trên Temporal của dự án (`localhost:17233`) nhưng dùng task queue riêng (`hoc-tq`, `hoc-nang-tq`), nên không đụng tới worker thật. Đã chạy thử ngày 09/11/2026 với temporalio 1.35.0 và Temporal Server 1.32.2.

| File trong phụ lục | Vai trò | Tương ứng trong dự án |
|---|---|---|
| `shared.py` | tên queue, kiểu dữ liệu | `packages/core/src/ingest/core/models.py`, `config.py` |
| `activities.py` | các activity | `packages/convert/src/ingest/convert/activities.py` |
| `workflow.py` | workflow | `packages/index/src/ingest/index/workflows/ingestion.py` |
| `worker.py` | chạy worker | `packages/convert/.../worker.py`, `packages/index/.../worker.py` |
| `client.py` | start, query, signal | `packages/api/src/ingest/api/workflow_client.py` |
| `replay.py` | kiểm tra code mới với lịch sử cũ | chưa có |

## Chạy thử

Mở ba terminal, cả ba đứng ở thư mục chứa `hoc/` (nằm trong repo để `uv run` dùng môi trường của dự án):

```bash
uv run python -m hoc.worker chinh     # terminal 1: workflow + activity nhẹ, poll hoc-tq
uv run python -m hoc.worker nang      # terminal 2: activity đọc trang, poll hoc-nang-tq
uv run python -m hoc.client chay bao-cao.pdf   # terminal 3
```

Workflow sẽ dừng ở bước chờ duyệt vì lô thứ ba đọc kém. Ở terminal khác:

```bash
uv run python -m hoc.client hoi bao-cao.pdf     # in ra CHO_DUYET
uv run python -m hoc.client duyet bao-cao.pdf   # gửi signal, terminal 3 in kết quả
```

Mở Temporal UI ở `http://localhost:18080`, tìm workflow `hoc-bao-cao.pdf` và xem tab Event History trong lúc làm các bước dưới đây.

## Bước 1. Dữ liệu đi qua Temporal

Xem `shared.py`.

- Tham số và kết quả của workflow, activity, signal, query đều được Temporal chuyển thành JSON và ghi vào lịch sử. Vì vậy chỉ dùng kiểu serialize được: `dataclass`, `list`, `str`, số.
- Giữ dữ liệu nhỏ. Lịch sử có giới hạn kích thước, và mỗi lần replay đều phải đọc lại nó. Dự án để nội dung file trên MinIO, còn qua Temporal chỉ truyền `doc_id`, key và các con số (`OcrBatch` chỉ chứa số trang).
- Đặt tên task queue thành hằng số dùng chung. Workflow gửi việc vào queue nào thì worker phải poll đúng tên đó. Sai một chữ là việc nằm chờ mãi mà không báo lỗi.

## Bước 2. Activity

Xem `activities.py`.

Activity là một hàm bình thường có `@activity.defn`. Trong activity được làm mọi thứ: đọc file, gọi API, ghi database. Temporal lo timeout và chạy lại khi lỗi.

Quy tắc:

- Activity có thể chạy nhiều lần cho cùng một việc (lỗi rồi thử lại, hoặc worker chết giữa chừng). Viết sao cho chạy lại không gây hại: ghi đè cùng một key thay vì nối thêm, kiểm tra đã làm chưa trước khi làm.
- Lỗi tạm thời thì cứ `raise`, Temporal sẽ thử lại theo `RetryPolicy`. `doc_lo` cố tình lỗi ở lần thử đầu của lô 1 để bạn thấy điều này.
- Lỗi chạy lại vẫn hỏng (file sai định dạng, có mật khẩu) thì raise `ApplicationError(..., non_retryable=True)`. `dem_trang` làm vậy với file không phải `.pdf`. Dự án gom các mã lỗi này ở `packages/core/src/ingest/core/errors.py`.
- `activity.info().attempt` cho biết đang là lần thử thứ mấy.
- Việc chạy lâu thì gọi `activity.heartbeat(...)` đều đặn. Xem bước 9.

## Bước 3. Workflow

Xem `workflow.py`.

Workflow chỉ mô tả thứ tự các bước. Temporal ghi lại kết quả từng bước vào lịch sử, và khi cần (worker mới, worker khởi động lại) sẽ chạy lại code workflow từ đầu rồi đối chiếu với lịch sử để về đúng chỗ. Vì vậy code workflow phải cho cùng một kết quả mỗi lần chạy với cùng lịch sử (deterministic).

Trong code workflow **không được**:

- đọc file, gọi mạng, truy vấn database: đưa vào activity
- dùng `datetime.now()`, `time.time()`: dùng `workflow.now()`
- dùng `random`, `uuid4()`: dùng `workflow.random()`, `workflow.uuid4()`
- dùng `time.sleep()`: dùng `await asyncio.sleep(...)` hoặc `await workflow.sleep(...)`, Temporal biến nó thành Timer bền, worker chết vẫn không mất
- tạo thread hay dùng biến toàn cục thay đổi được

Python SDK chạy workflow trong sandbox và sẽ chặn phần lớn các lỗi trên. Vì sandbox nạp lại module, phần import activity và kiểu dữ liệu phải bọc trong `workflow.unsafe.imports_passed_through()`.

Các quy tắc khác:

- Mỗi lần gọi `workflow.execute_activity` phải có `start_to_close_timeout` (hoặc `schedule_to_close_timeout`). Không có thì SDK báo lỗi.
- Trạng thái của workflow (bước hiện tại, quyết định duyệt) lưu trong thuộc tính của class (`self._buoc`, `self._duyet`).
- Raise `ApplicationError` trong workflow làm workflow kết thúc ở trạng thái Failed.
- Muốn chọn worker cho từng activity thì truyền `task_queue=...`. Không truyền thì activity dùng chung queue với workflow. Ở đây `dem_trang` và `ghep` chạy trên `hoc-tq`, còn `doc_lo` sang `hoc-nang-tq`.

## Bước 4. Worker

Xem `worker.py`.

- Worker là tiến trình của bạn. Nó poll một task queue và chạy những workflow, activity đã đăng ký với nó. Temporal Server không chạy code của bạn.
- Một worker có thể chạy cả workflow lẫn activity. Worker `chinh` ở đây làm cả hai, giống Indexing Worker trong dự án. Không cần worker riêng cho workflow.
- Mỗi worker chỉ nghe một queue. Muốn nghe hai queue thì tạo hai `Worker` trong cùng tiến trình, như `packages/index/src/ingest/index/worker.py` làm với `ingest-tq` và `index-tq`.
- Mọi worker cùng poll một queue phải đăng ký cùng một bộ workflow và activity. Worker nhận một task mà nó không đăng ký thì task đó lỗi.
- `max_concurrent_activities` giới hạn số activity chạy cùng lúc trên một worker. Muốn chạy nhanh hơn thì bật thêm worker cùng queue, không phải sửa gì ở server.

## Bước 5. Client

Xem `client.py`.

- `client.start_workflow(XuLyTaiLieu.run, input, id=..., task_queue=...)` tạo workflow và trả về ngay. API của dự án làm vậy để không bắt người dùng chờ.
- `id` là khoá của workflow. Hai workflow cùng `id` không thể chạy cùng lúc. Dự án đặt `id` theo `doc_id` để một tài liệu không bị xử lý hai lần.
- `handle.result()` chờ workflow xong và trả kết quả.
- `handle.query(...)` hỏi trạng thái, `handle.signal(...)` gửi dữ liệu vào workflow đang chạy. Xem bước 10.

## Bước 6. Đọc Event History

Lần chạy thử có 41 event:

- `WorkflowExecutionStarted`: client vừa start
- 7 bộ `WorkflowTaskScheduled` → `Started` → `Completed`: mỗi lần workflow thức dậy chạy tiếp code
- 5 bộ `ActivityTaskScheduled` → `Started` → `Completed`: `dem_trang`, ba lần `doc_lo`, `ghep`
- `TimerStarted` và `TimerCanceled`: timeout 10 phút của `wait_condition`, bị huỷ khi signal tới
- `WorkflowExecutionSignaled`: signal duyệt
- `WorkflowExecutionCompleted`

Lịch sử không có event riêng cho mỗi lần thử lại. `ActivityTaskStarted` được ghi khi activity kết thúc, kèm số lần thử (`attempt`) và lỗi lần trước (`lastFailure`).

## Bước 7. Retry và timeout

- `RetryPolicy(initial_interval=1s, maximum_attempts=5)` trên `doc_lo`: lỗi thì chờ 1 giây rồi thử lại, khoảng chờ tăng dần, tối đa 5 lần.
- Activity không đặt `retry_policy` vẫn được thử lại, không giới hạn số lần, cho tới khi hết `schedule_to_close_timeout` (nếu có đặt).
- Lỗi `non_retryable` thì dừng ngay. Thử `uv run python -m hoc.client chay anh.png`: workflow fail sau đúng một lần thử với `UNSUPPORTED_FORMAT`.
- `start_to_close_timeout` là thời gian tối đa cho **một lần thử**. Quá hạn thì lần đó tính là lỗi và được thử lại.

## Bước 8. Chạy song song

```python
ket_qua = await asyncio.gather(*(workflow.execute_activity(doc_lo, lo, ...) for lo in cac_lo))
```

Ba lô được đưa vào `hoc-nang-tq` cùng lúc. Worker `nang` cho phép 2 activity cùng lúc, nên hai lô chạy trước, lô còn lại chờ. Bật thêm một worker `nang` ở terminal khác thì cả ba chạy cùng lúc.

Mỗi khi một lô xong, workflow thức dậy một lần (một workflow task), thấy `gather` chưa đủ thì ngủ tiếp. Dự án làm y như vậy với `parse_document` và các lô `ocr_pages`.

## Bước 9. Heartbeat và worker chết giữa chừng

Thử: chạy lại từ đầu với tên file khác, ví dụ `bao-cao-2.pdf`. Khi `hoi` trả về `DOC_TRANG`, tắt worker `nang` (Ctrl+C), chờ khoảng 10 giây rồi bật lại.

Điều xảy ra:

- Worker chết thì không còn heartbeat. Sau `heartbeat_timeout` (5 giây), server coi lần thử đó là lỗi và đưa việc lại vào hàng đợi.
- Worker bật lại nhận việc. `activity.info().heartbeat_details` chứa giá trị heartbeat cuối cùng của lần thử trước, nên `doc_lo` đọc tiếp từ trang đang dở thay vì đọc lại từ đầu.
- Không có heartbeat thì server chỉ biết worker chết khi hết `start_to_close_timeout` (2 phút).

Trong lần chạy thử, lô 1 có `attempt` 3: lần 1 lỗi giả lập, lần 2 bị tắt worker, lần 3 xong.

## Bước 10. Signal, query và chờ người

- `@workflow.query` chỉ đọc trạng thái, không được thay đổi gì, không ghi vào lịch sử.
- `@workflow.signal` nhận dữ liệu từ bên ngoài, ghi vào lịch sử thành `WorkflowExecutionSignaled`. Signal đã gửi không sửa được. Muốn đổi ý thì gửi signal mới, và code workflow quyết định xử lý nó thế nào.
- `await workflow.wait_condition(lambda: ..., timeout=...)` cho workflow ngủ tới khi điều kiện đúng. Lúc ngủ, workflow không chiếm worker nào, có thể chờ nhiều ngày. Hết timeout thì raise `TimeoutError`.
- Nếu cần biết workflow đã nhận và xử lý xong (ví dụ trả lỗi khi tài liệu không còn ở bước chờ duyệt) thì dùng `@workflow.update` thay cho signal.

## Bước 11. Sửa code workflow khi còn workflow đang chạy

Workflow đang chạy dở sẽ được replay bằng code mới. Nếu code mới tạo ra chuỗi lệnh khác lịch sử cũ thì workflow đó bị kẹt.

Kiểm tra bằng `replay.py`:

```bash
temporal workflow show --address localhost:17233 -w hoc-bao-cao.pdf --output json > lich-su.json
uv run python -m hoc.replay lich-su.json      # Replay OK
```

Thử chèn `await workflow.sleep(timedelta(seconds=1))` ngay sau dòng `self._buoc = "DEM_TRANG"` rồi chạy lại lệnh trên. Kết quả:

```
NondeterminismError: ... Timer machine does not handle this event: HistoryEvent(id: 5, ActivityTaskScheduled)
```

Lịch sử cũ ghi bước 5 là `ActivityTaskScheduled`, còn code mới lại muốn tạo Timer trước. Cách sửa là bọc phần mới:

```python
if workflow.patched("them-buoc-cho"):
    await workflow.sleep(timedelta(seconds=1))
```

Workflow cũ replay sẽ bỏ qua nhánh này, còn workflow mới thì chạy nó. Replay lại báo OK. Khi không còn workflow cũ nào chạy, đổi `patched` thành `workflow.deprecate_patch("them-buoc-cho")`, sau đó mới xoá hẳn.

Chỉ sửa nội dung bên trong activity thì không cần `patched`, vì code activity không bị replay.

## Tóm tắt quy tắc

- Workflow chỉ chứa thứ tự các bước và quyết định. Mọi việc chạm tới thế giới bên ngoài nằm trong activity.
- Code workflow phải deterministic: không I/O, không giờ hệ thống, không random, không `time.sleep`.
- Activity phải chạy lại được nhiều lần mà không gây hại.
- Mỗi activity có timeout. Việc lâu thì có heartbeat.
- Lỗi vĩnh viễn thì `non_retryable`.
- Dữ liệu qua Temporal phải nhỏ và serialize được. Nội dung lớn để ở storage, chỉ truyền key.
- Tên task queue dùng chung một hằng số. Các worker cùng queue đăng ký giống nhau.
- Đổi thứ tự hay thêm bước trong workflow thì dùng `workflow.patched` và kiểm tra bằng replay.

## Bài tập

1. Thêm activity `luu_ket_qua` ghi Markdown ra file sau bước `ghep`. Nhớ làm sao để chạy lại không tạo file trùng.
2. Đổi `heartbeat_timeout` thành 30 giây rồi làm lại bước 9. So sánh thời gian chờ trước khi lô bị chạy lại.
3. Thay signal `duyet` bằng `@workflow.update` có validator, từ chối khi workflow không ở bước `CHO_DUYET`.
4. Lưu lịch sử của một workflow đã chạy, thêm một activity vào giữa workflow, chạy `replay.py` để thấy lỗi, rồi sửa bằng `workflow.patched`.

## Phụ lục: code mẫu

Đã chạy thử và qua `ruff` ngày 09/11/2026.

### `hoc/shared.py`

```python
"""Tên task queue và kiểu dữ liệu dùng chung giữa workflow, activity, worker và client."""

from dataclasses import dataclass

TQ_CHINH = "hoc-tq"  # workflow và activity nhẹ
TQ_NANG = "hoc-nang-tq"  # activity nặng (đọc trang)


@dataclass
class TaiLieu:
    ten: str


@dataclass
class LoTrang:
    ten: str
    lo: int
    trang: list[int]


@dataclass
class KetQuaLo:
    lo: int
    noi_dung: str
    tin_cay: float
```

### `hoc/activities.py`

```python
"""Activity: hàm bình thường, được làm I/O, gọi mạng, đọc file. Temporal lo retry và timeout."""

import asyncio

from temporalio import activity
from temporalio.exceptions import ApplicationError

from hoc.shared import KetQuaLo, LoTrang, TaiLieu


@activity.defn
async def dem_trang(tl: TaiLieu) -> int:
    activity.logger.info("Đếm trang %s", tl.ten)
    if not tl.ten.endswith(".pdf"):
        # Lỗi chạy lại vẫn hỏng: đánh dấu non_retryable để Temporal không thử lại
        raise ApplicationError(
            f"Không hỗ trợ {tl.ten}", type="UNSUPPORTED_FORMAT", non_retryable=True
        )
    return 25


@activity.defn
async def doc_lo(lo: LoTrang) -> KetQuaLo:
    info = activity.info()
    # Lần thử đầu của lô 1 luôn lỗi, để thấy Temporal tự chạy lại
    if lo.lo == 1 and info.attempt == 1:
        raise RuntimeError("OCR lỗi tạm thời")
    # Lần thử trước đã heartbeat tới trang nào thì đọc tiếp từ đó
    da_xong = info.heartbeat_details[0] if info.heartbeat_details else 0
    for i in range(da_xong, len(lo.trang)):
        await asyncio.sleep(1)  # giả lập OCR một trang
        activity.heartbeat(i + 1)
    noi_dung = "\n".join(f"<!-- page: {t + 1} --> chữ trang {t + 1}" for t in lo.trang)
    tin_cay = 0.4 if 20 in lo.trang else 0.95  # lô có trang 21 đọc kém
    return KetQuaLo(lo.lo, noi_dung, tin_cay)


@activity.defn
async def ghep(ket_qua: list[KetQuaLo]) -> str:
    return "\n".join(k.noi_dung for k in sorted(ket_qua, key=lambda k: k.lo))
```

### `hoc/workflow.py`

```python
"""Workflow: chỉ mô tả thứ tự các bước. Không I/O, không giờ hệ thống, không random."""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from hoc.activities import dem_trang, doc_lo, ghep
    from hoc.shared import TQ_NANG, LoTrang, TaiLieu


@workflow.defn
class XuLyTaiLieu:
    def __init__(self) -> None:
        self._buoc = "MOI"
        self._duyet: bool | None = None

    @workflow.query
    def buoc(self) -> str:
        return self._buoc

    @workflow.signal
    def duyet(self, dong_y: bool) -> None:
        self._duyet = dong_y

    @workflow.run
    async def run(self, tl: TaiLieu) -> str:
        self._buoc = "DEM_TRANG"
        so_trang = await workflow.execute_activity(
            dem_trang, tl, start_to_close_timeout=timedelta(seconds=10)
        )

        self._buoc = "DOC_TRANG"
        cac_lo = [
            LoTrang(tl.ten, n, list(range(dau, min(dau + 10, so_trang))))
            for n, dau in enumerate(range(0, so_trang, 10))
        ]
        ket_qua = await asyncio.gather(
            *(
                workflow.execute_activity(
                    doc_lo,
                    lo,
                    task_queue=TQ_NANG,  # việc nặng sang queue khác, worker khác nhận
                    start_to_close_timeout=timedelta(minutes=2),
                    heartbeat_timeout=timedelta(seconds=5),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=1), maximum_attempts=5
                    ),
                )
                for lo in cac_lo
            )
        )

        if min(k.tin_cay for k in ket_qua) < 0.6:
            self._buoc = "CHO_DUYET"
            try:
                await workflow.wait_condition(
                    lambda: self._duyet is not None, timeout=timedelta(minutes=10)
                )
            except TimeoutError:
                self._duyet = False
            if not self._duyet:
                raise ApplicationError("Người duyệt từ chối", type="REJECTED", non_retryable=True)

        self._buoc = "GHEP"
        md = await workflow.execute_activity(
            ghep, list(ket_qua), start_to_close_timeout=timedelta(seconds=10)
        )
        self._buoc = "XONG"
        return md
```

### `hoc/worker.py`

```python
"""Chạy worker. `chinh`: workflow + activity nhẹ trên hoc-tq. `nang`: doc_lo trên hoc-nang-tq."""

import argparse
import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from hoc.activities import dem_trang, doc_lo, ghep
from hoc.shared import TQ_CHINH, TQ_NANG
from hoc.workflow import XuLyTaiLieu


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("vai", choices=["chinh", "nang"])
    p.add_argument("--address", default="localhost:17233")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    client = await Client.connect(a.address)
    if a.vai == "chinh":
        w = Worker(
            client, task_queue=TQ_CHINH, workflows=[XuLyTaiLieu], activities=[dem_trang, ghep]
        )
    else:
        w = Worker(client, task_queue=TQ_NANG, activities=[doc_lo], max_concurrent_activities=2)
    print(f"Worker {a.vai} đang poll {w.task_queue}. Ctrl+C để tắt.")
    await w.run()


if __name__ == "__main__":
    asyncio.run(main())
```

### `hoc/client.py`

```python
"""Client: bắt đầu workflow, hỏi tiến độ (query), gửi duyệt (signal)."""

import argparse
import asyncio

from temporalio.client import Client

from hoc.shared import TQ_CHINH, TaiLieu
from hoc.workflow import XuLyTaiLieu


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("lenh", choices=["chay", "hoi", "duyet", "tu-choi"])
    p.add_argument("ten", help="tên file, ví dụ bao-cao.pdf")
    p.add_argument("--address", default="localhost:17233")
    p.add_argument("--khong-cho", action="store_true", help="chay: không chờ kết quả")
    a = p.parse_args()
    client = await Client.connect(a.address)
    wid = f"hoc-{a.ten}"

    if a.lenh == "chay":
        h = await client.start_workflow(
            XuLyTaiLieu.run, TaiLieu(a.ten), id=wid, task_queue=TQ_CHINH
        )
        print(f"Đã start {wid}, run_id={h.result_run_id}")
        if not a.khong_cho:
            print(await h.result())
        return
    h = client.get_workflow_handle(wid)
    if a.lenh == "hoi":
        print(await h.query(XuLyTaiLieu.buoc))
    else:
        await h.signal(XuLyTaiLieu.duyet, a.lenh == "duyet")
        print("Đã gửi signal")


if __name__ == "__main__":
    asyncio.run(main())
```

### `hoc/replay.py`

```python
"""Chạy lại lịch sử thật bằng code workflow hiện tại. Lỗi NonDeterminism nghĩa là code mới
không khớp lịch sử cũ: workflow đang chạy dở sẽ kẹt khi worker deploy bản này.

    temporal workflow show --address localhost:17233 -w hoc-bao-cao.pdf --output json > lich-su.json
    python -m hoc.replay lich-su.json
"""

import asyncio
import sys
from pathlib import Path

from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer

from hoc.workflow import XuLyTaiLieu


async def main(path: str) -> None:
    history = WorkflowHistory.from_json("hoc-replay", Path(path).read_text())
    await Replayer(workflows=[XuLyTaiLieu]).replay_workflow(history)
    print("Replay OK: code hiện tại khớp lịch sử")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
```
