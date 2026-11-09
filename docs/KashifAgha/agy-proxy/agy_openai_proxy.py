#!/usr/bin/env python3
"""OpenAI-compatible proxy around the `agy` CLI.

Each /v1/chat/completions request runs a fresh `agy -p` session in an empty
workspace and returns the answer in OpenAI format (plain JSON or SSE).

Env:
  AGY_PROXY_HOST   (default 127.0.0.1)
  AGY_PROXY_PORT   (default 8787)
  AGY_MODEL        default agy model when the request names an unknown one
                   (default gemini-3.8-flash-low)
  AGY_WORKSPACE    working dir for agy sessions (default ./workspace)
  AGY_MAX_PARALLEL max concurrent agy processes (default 2)
  AGY_TIMEOUT      seconds per agy call (default 300)
  AGY_PROXY_KEY    if set, require "Authorization: Bearer <key>"
"""

import json
import os
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = os.environ.get("AGY_PROXY_HOST", "127.0.0.1")
PORT = int(os.environ.get("AGY_PROXY_PORT", "8787"))
DEFAULT_MODEL = os.environ.get("AGY_MODEL", "gemini-3.8-flash-low")
WORKSPACE = Path(os.environ.get("AGY_WORKSPACE", Path(__file__).parent / "workspace"))
TIMEOUT = int(os.environ.get("AGY_TIMEOUT", "300"))
PROXY_KEY = os.environ.get("AGY_PROXY_KEY", "")
SLOTS = threading.Semaphore(int(os.environ.get("AGY_MAX_PARALLEL", "2")))

KNOWN_MODELS = [
    "gemini-3.8-flash-high",
    "gemini-3.8-flash-medium",
    "gemini-3.8-flash-low",
    "claude-sonnet-4-6",
    "claude-opus-4-6-thinking",
    "gpt-oss-120b-medium",
]

PREAMBLE = (
    "You are being used as a plain text-completion API. Do not use any tools, "
    "do not read or write files, do not run commands. Reply only with the "
    "assistant message that should follow the conversation below, with no "
    "extra commentary.\n\n"
)


def content_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # OpenAI content parts
        return "\n".join(p.get("text", "") for p in content if p.get("type") == "text")
    return ""


def build_prompt(messages):
    parts = [PREAMBLE]
    for m in messages:
        role = m.get("role", "user").upper()
        parts.append(f"### {role}\n{content_text(m.get('content'))}\n")
    parts.append("### ASSISTANT\n")
    return "\n".join(parts)


def run_agy(prompt, model):
    cmd = ["agy", "-p", prompt, "--output-format", "json",
           "--model", model, "--disable-slash-commands", "--sandbox"]
    with SLOTS:
        proc = subprocess.run(cmd, cwd=WORKSPACE, capture_output=True,
                              text=True, timeout=TIMEOUT)
    out = proc.stdout.strip()
    try:
        data = json.loads(out.splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        raise RuntimeError(f"agy exit {proc.returncode}: {proc.stderr[-500:] or out[-500:]}")
    if data.get("status") != "SUCCESS":
        raise RuntimeError(f"agy status {data.get('status')}: {out[-500:]}")
    return data


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print(f"[{time.strftime('%H:%M:%S')}] {fmt % args}", flush=True)

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        if not PROXY_KEY:
            return True
        if self.headers.get("Authorization", "") == f"Bearer {PROXY_KEY}":
            return True
        self._json(401, {"error": {"message": "invalid api key", "type": "auth_error"}})
        return False

    def do_GET(self):
        if not self._authorized():
            return
        if self.path.rstrip("/") in ("/v1/models", "/models"):
            self._json(200, {"object": "list", "data": [
                {"id": m, "object": "model", "owned_by": "agy"} for m in KNOWN_MODELS]})
        elif self.path.rstrip("/") in ("", "/health"):
            self._json(200, {"ok": True})
        else:
            self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        if not self._authorized():
            return
        if self.path.rstrip("/") not in ("/v1/chat/completions", "/chat/completions"):
            self._json(404, {"error": {"message": "not found"}})
            return
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        except json.JSONDecodeError:
            self._json(400, {"error": {"message": "bad json"}})
            return

        model = req.get("model") if req.get("model") in KNOWN_MODELS else DEFAULT_MODEL
        try:
            data = run_agy(build_prompt(req.get("messages", [])), model)
        except Exception as e:  # noqa: BLE001
            self.log_message("agy error: %s", e)
            self._json(502, {"error": {"message": str(e), "type": "upstream_error"}})
            return

        text = data.get("response", "").rstrip("\n")
        u = data.get("usage", {})
        usage = {"prompt_tokens": u.get("input_tokens", 0),
                 "completion_tokens": u.get("output_tokens", 0),
                 "total_tokens": u.get("total_tokens", 0)}
        cid, created = f"chatcmpl-{uuid.uuid4().hex}", int(time.time())

        if not req.get("stream"):
            self._json(200, {
                "id": cid, "object": "chat.completion", "created": created, "model": model,
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": text}}],
                "usage": usage})
            return

        # agy returns the whole answer at once, so stream it as one content chunk.
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        base = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model}
        chunks = [
            {**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": text},
                                  "finish_reason": None}]},
            {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ]
        if (req.get("stream_options") or {}).get("include_usage"):
            chunks.append({**base, "choices": [], "usage": usage})
        for c in chunks:
            self.wfile.write(f"data: {json.dumps(c, ensure_ascii=False)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True


if __name__ == "__main__":
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    print(f"agy proxy on http://{HOST}:{PORT}/v1  (default model {DEFAULT_MODEL}, workspace {WORKSPACE})", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
