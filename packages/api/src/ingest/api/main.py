"""Chạy Ingestion API bằng uvicorn. Entry point `ingest-api`."""


def serve(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:  # noqa: S104
    import uvicorn

    uvicorn.run(
        "ingest.api.app:create_default_app", factory=True, host=host, port=port, reload=reload
    )


def main() -> None:
    import os

    serve(port=int(os.environ.get("INGEST_API_PORT", "8000")))


if __name__ == "__main__":
    main()
