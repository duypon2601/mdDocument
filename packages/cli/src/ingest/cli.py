"""CLI `ingest`: gọi API qua httpx, chạy API và worker.

Chỉ phụ thuộc httpx và typer. Lệnh `api` và `worker` cần cài thêm package tương ứng
(ingest-api, ingest-convert, ingest-index); ở root workspace thì đã có đủ.
"""

import json
from pathlib import Path
from typing import Annotated

import httpx
import typer

DEFAULT_API_URL = "http://localhost:8000"

app = typer.Typer(help="Document Ingestion CLI", no_args_is_help=True)
worker_app = typer.Typer(help="Chạy worker", no_args_is_help=True)
app.add_typer(worker_app, name="worker")

ApiOpt = Annotated[str | None, typer.Option("--api-url", envvar="INGEST_API_URL", help="URL API")]


def _base(api_url: str | None) -> str:
    return (api_url or DEFAULT_API_URL).rstrip("/")


def _call(method: str, url: str, **kw) -> dict:
    try:
        r = httpx.request(method, url, timeout=120, **kw)
    except httpx.HTTPError as e:
        typer.echo(f"Không gọi được API: {e}", err=True)
        raise typer.Exit(2) from e
    if r.status_code >= 400:
        typer.echo(f"Lỗi {r.status_code}: {r.text}", err=True)
        raise typer.Exit(1)
    return r.json()


def _require(module: str, dist: str) -> None:
    import importlib.util

    if importlib.util.find_spec(module) is None:
        typer.echo(f"Thiếu package {dist}. Cài bằng: uv sync --package {dist}", err=True)
        raise typer.Exit(2)


def _show(data: dict) -> None:
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


@app.command()
def upload(
    paths: Annotated[list[Path], typer.Argument(exists=True, dir_okay=False, readable=True)],
    api_url: ApiOpt = None,
) -> None:
    """Upload một hoặc nhiều file."""
    base = _base(api_url)
    if len(paths) == 1:
        p = paths[0]
        _show(_call("POST", f"{base}/documents", files={"file": (p.name, p.read_bytes())}))
        return
    files = [("files", (p.name, p.read_bytes())) for p in paths]
    _show(_call("POST", f"{base}/documents/batch", files=files))


@app.command()
def status(doc_id: str, api_url: ApiOpt = None) -> None:
    """Xem trạng thái và tiến độ một tài liệu."""
    _show(_call("GET", f"{_base(api_url)}/documents/{doc_id}"))


@app.command("list")
def list_cmd(
    status: Annotated[str | None, typer.Option(help="Lọc theo trạng thái")] = None,
    q: Annotated[str | None, typer.Option(help="Tìm theo tên file")] = None,
    limit: int = 20,
    offset: int = 0,
    api_url: ApiOpt = None,
) -> None:
    """Liệt kê tài liệu."""
    params = {"limit": limit, "offset": offset}
    if status:
        params["status"] = status
    if q:
        params["q"] = q
    data = _call("GET", f"{_base(api_url)}/documents", params=params)
    for d in data["items"]:
        typer.echo(f"{d['doc_id'][:12]}  {d['status']:<12} {d['chunk_count']:>5}  {d['file_name']}")
    typer.echo(f"({len(data['items'])}/{data['total']})")


@app.command()
def review(
    doc_id: str,
    decision: Annotated[str, typer.Argument(help="approve hoặc reject")],
    api_url: ApiOpt = None,
) -> None:
    """Duyệt hoặc bỏ tài liệu đang NEEDS_REVIEW."""
    _show(
        _call(
            "POST",
            f"{_base(api_url)}/documents/{doc_id}/review",
            params={"decision": decision},
        )
    )


@app.command()
def reindex(doc_id: str, api_url: ApiOpt = None) -> None:
    """Re-index tài liệu đã INDEXED với index_version mới."""
    _show(_call("POST", f"{_base(api_url)}/documents/{doc_id}/reindex"))


@app.command()
def cancel(doc_id: str, api_url: ApiOpt = None) -> None:
    """Huỷ workflow đang chạy."""
    _show(_call("POST", f"{_base(api_url)}/documents/{doc_id}/cancel"))


@app.command()
def api(
    host: str = "0.0.0.0",  # noqa: S104
    port: int = 8000,
    reload: bool = False,
) -> None:
    """Chạy Ingestion API (uvicorn)."""
    _require("ingest.api", "ingest-api")
    from ingest.api.main import serve

    serve(host=host, port=port, reload=reload)


@worker_app.command("convert")
def worker_convert() -> None:
    """Worker convert-tq: activity chuyển đổi, OCR."""
    _require("ingest.convert", "ingest-convert")
    from ingest.convert import worker

    worker.main()


@worker_app.command("index")
def worker_index() -> None:
    """Worker ingest-tq (workflow, update_status) và index-tq (chunk, embed, upsert)."""
    _require("ingest.index", "ingest-index")
    from ingest.index import worker

    worker.main()


if __name__ == "__main__":
    app()
