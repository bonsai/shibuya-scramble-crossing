#!/usr/bin/env python3
"""
Colab 制御 API + Cloudflare Tunnel

CF UI からバッチを操作するための軽量 HTTP サーバ。
cloudflared で公開 URL を取得し、CF Worker に登録する。

Colab 例:
  !pip install -q pyyaml
  !wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O /usr/local/bin/cloudflared
  !chmod +x /usr/local/bin/cloudflared

  import os
  os.environ["R2_ACCOUNT_ID"] = "..."
  os.environ["R2_ACCESS_KEY_ID"] = "..."
  os.environ["R2_SECRET_ACCESS_KEY"] = "..."
  os.environ["CF_BASE_URL"] = "https://your-worker.example.workers.dev"  # デプロイ先
  os.environ["COLAB_TOKEN"] = "optional-shared-secret"

  !python /content/tunnel_server.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = int(os.environ.get("COLAB_PORT", "8765"))
TOKEN = os.environ.get("COLAB_TOKEN", "").strip()
CF_BASE_URL = os.environ.get("CF_BASE_URL", "").rstrip("/")
BATCH_SCRIPT = Path(os.environ.get("BATCH_SCRIPT", "/content/batch_3dgs.py"))
BATCH_CONFIG = Path(os.environ.get("BATCH_CONFIG", "/content/batch_config.yaml"))

_state = {
    "status": "idle",  # idle | running | done | error
    "message": "",
    "started_at": None,
    "finished_at": None,
    "log_tail": [],
    "tunnel_url": None,
}
_lock = threading.Lock()
_proc: subprocess.Popen | None = None


def _append_log(line: str) -> None:
    with _lock:
        _state["log_tail"].append(line.rstrip())
        _state["log_tail"] = _state["log_tail"][-80:]


def _set_status(status: str, message: str = "") -> None:
    with _lock:
        _state["status"] = status
        _state["message"] = message
        if status == "running":
            _state["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            _state["finished_at"] = None
        if status in ("done", "error"):
            _state["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _check_auth(handler: BaseHTTPRequestHandler) -> bool:
    if not TOKEN:
        return True
    auth = handler.headers.get("Authorization", "")
    if auth == f"Bearer {TOKEN}":
        return True
    if handler.headers.get("X-Colab-Token") == TOKEN:
        return True
    return False


def _run_batch(extra_args: list[str]) -> None:
    global _proc
    _set_status("running", "batch started")
    _append_log("$ python batch_3dgs.py " + " ".join(extra_args))

    cmd = [sys.executable, str(BATCH_SCRIPT), "--config", str(BATCH_CONFIG), *extra_args]
    try:
        _proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert _proc.stdout is not None
        for line in _proc.stdout:
            _append_log(line)
        code = _proc.wait()
        if code == 0:
            _set_status("done", f"exit {code}")
        else:
            _set_status("error", f"exit {code}")
    except Exception as e:
        _append_log(f"ERROR: {e}")
        _set_status("error", str(e))
    finally:
        _proc = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        pass  # quiet

    def _send(self, code: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Colab-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Colab-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path in ("/", "/health"):
            self._send(200, {"ok": True, "service": "shibuya-colab-tunnel"})
            return
        if self.path == "/status":
            if not _check_auth(self):
                self._send(401, {"error": "unauthorized"})
                return
            with _lock:
                snap = dict(_state)
                snap["log_tail"] = list(_state["log_tail"])
            self._send(200, snap)
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not _check_auth(self):
            self._send(401, {"error": "unauthorized"})
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {}

        if self.path == "/batch":
            with _lock:
                if _state["status"] == "running":
                    self._send(409, {"error": "already running", "status": _state})
                    return

            extra: list[str] = []
            if payload.get("force"):
                extra.append("--force")
            if payload.get("dry_run"):
                extra.append("--dry-run")
            if payload.get("skip_train"):
                extra.append("--skip-train")
            if payload.get("prefix"):
                extra.extend(["--prefix", str(payload["prefix"])])

            t = threading.Thread(target=_run_batch, args=(extra,), daemon=True)
            t.start()
            self._send(202, {"ok": True, "message": "batch started", "args": extra})
            return

        if self.path == "/stop":
            global _proc
            if _proc and _proc.poll() is None:
                _proc.terminate()
                _append_log("terminated by /stop")
                _set_status("error", "stopped")
                self._send(200, {"ok": True, "message": "stopping"})
            else:
                self._send(200, {"ok": True, "message": "not running"})
            return

        self._send(404, {"error": "not found"})


def start_cloudflared(local_port: int) -> str:
    """quick tunnel を立て、https URL を返す。"""
    bin_path = os.environ.get("CLOUDFLARED", "cloudflared")
    proc = subprocess.Popen(
        [bin_path, "tunnel", "--url", f"http://{HOST}:{local_port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert proc.stdout is not None
    url = None
    deadline = time.time() + 60
    for line in proc.stdout:
        print(line.rstrip())
        m = re.search(r"(https://[a-z0-9-]+\.trycloudflare\.com)", line)
        if m:
            url = m.group(1)
            break
        if time.time() > deadline:
            break
    if not url:
        raise RuntimeError("cloudflared tunnel URL を取得できませんでした")

    # 残りのlogを吸い続けてプロセスを生かす
    def _drain():
        for _ in proc.stdout:
            pass

    threading.Thread(target=_drain, daemon=True).start()
    return url


def register_with_cf(tunnel_url: str) -> None:
    if not CF_BASE_URL:
        print("CF_BASE_URL 未設定 — 手動で UI にトンネル URL を貼ってください:", tunnel_url)
        return
    payload = json.dumps({"tunnel_url": tunnel_url, "token": TOKEN or None}).encode()
    req = urllib.request.Request(
        f"{CF_BASE_URL}/api/colab/register",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            print("registered:", res.read().decode())
    except urllib.error.URLError as e:
        print("register failed:", e)
        print("tunnel URL:", tunnel_url)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"local API http://{HOST}:{PORT}")

    tunnel_url = start_cloudflared(PORT)
    with _lock:
        _state["tunnel_url"] = tunnel_url
    print("tunnel:", tunnel_url)
    register_with_cf(tunnel_url)

    print("ready — Ctrl+C to stop")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("bye")


if __name__ == "__main__":
    main()
