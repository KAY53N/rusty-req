"""Check rusty-req 0.3.32 timeout and result behaviour.

Run from the repo root:

    uv run --python 3.12 --with 'rusty-req==0.3.32' --no-project python tests/test_timeout_0_3_32.py

`--no-project` is required. This repo is itself the rusty-req package, so a
plain `uv run` builds the local source instead of installing 0.3.32 from PyPI.

Cases:
  - timeout below 3s is honoured, not raised to 3s
  - timeout above 30s is honoured, not capped at 30s
  - a fast 200 returns the body
  - a non-2xx status returns HttpStatusError
  - a connection failure returns HttpError

Requires the installed package to be exactly 0.3.32.
"""

import asyncio
import importlib.metadata
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import rusty_req

EXPECTED_VERSION = "0.3.32"


class SleepHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/sleep/"):
            time.sleep(float(path.rsplit("/", 1)[-1]))
            body = b"ok"
            status = 200
        elif path == "/status/500":
            body = b"boom"
            status = 500
        else:
            body = b"missing"
            status = 404
        try:
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # Client already gave up on its timeout. Nothing to send back.
            return

    def log_message(self, *_args):
        return

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            return


def start_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), SleepHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def fail(name, detail):
    raise AssertionError(f"{name}: {detail}")


def check_version():
    installed = importlib.metadata.version("rusty-req")
    if installed != EXPECTED_VERSION:
        fail("version", f"installed {installed}, expected {EXPECTED_VERSION}")
    print(f"PASS version {installed}")


async def check_under_3s(base):
    timeout = 0.5
    started = time.perf_counter()
    result = await rusty_req.fetch_single(
        f"{base}/sleep/5", timeout=timeout, tag="under-3s"
    )
    elapsed = time.perf_counter() - started
    exc = result["exception"]
    if not (0.4 <= elapsed < 1.5):
        fail("under-3s", f"returned after {elapsed:.2f}s, old floor was 3s")
    if exc.get("type") != "HttpError":
        fail("under-3s", f"exception type {exc.get('type')}, expected HttpError")
    if "timed out" not in exc.get("message", ""):
        fail("under-3s", f"message does not say timed out: {exc.get('message')}")
    if result["http_status"] != 0:
        fail("under-3s", f"http_status {result['http_status']}, expected 0")
    print(f"PASS under-3s  timeout={timeout} wall={elapsed:.2f}s type={exc['type']}")


async def check_over_30s(base):
    timeout = 35.0
    started = time.perf_counter()
    result = await rusty_req.fetch_single(
        f"{base}/sleep/60", timeout=timeout, tag="over-30s"
    )
    elapsed = time.perf_counter() - started
    exc = result["exception"]
    if elapsed < 32:
        fail("over-30s", f"capped early at {elapsed:.2f}s, client 30s cap is back")
    if not (32 <= elapsed < 40):
        fail("over-30s", f"returned after {elapsed:.2f}s, expected about {timeout}s")
    if exc.get("type") != "HttpError":
        fail("over-30s", f"exception type {exc.get('type')}, expected HttpError")
    if "timed out" not in exc.get("message", ""):
        fail("over-30s", f"message does not say timed out: {exc.get('message')}")
    print(f"PASS over-30s  timeout={timeout} wall={elapsed:.2f}s type={exc['type']}")


async def check_success(base):
    started = time.perf_counter()
    result = await rusty_req.fetch_single(
        f"{base}/sleep/0.2", timeout=5, tag="success"
    )
    elapsed = time.perf_counter() - started
    exc = result["exception"]
    if result["http_status"] != 200:
        fail("success", f"http_status {result['http_status']}")
    if result["response"] != "ok":
        fail("success", f"response {result['response']!r}")
    if exc != {}:
        fail("success", f"exception {exc}")
    if elapsed >= 3:
        fail("success", f"fast request took {elapsed:.2f}s")
    print(f"PASS success   status=200 wall={elapsed:.2f}s response={result['response']!r}")


async def check_http_error(base):
    result = await rusty_req.fetch_single(
        f"{base}/status/500", timeout=5, tag="http-500"
    )
    exc = result["exception"]
    if result["http_status"] != 500:
        fail("http-500", f"http_status {result['http_status']}")
    if exc.get("type") != "HttpStatusError":
        fail("http-500", f"exception type {exc.get('type')}")
    if exc.get("message") != "HTTP status error: 500":
        fail("http-500", f"message {exc.get('message')!r}")
    if result["response"] != "":
        fail("http-500", f"response should be empty, got {result['response']!r}")
    print(f"PASS http-500  status=500 type={exc['type']} message={exc['message']!r}")


async def check_connect_error():
    result = await rusty_req.fetch_single(
        "http://127.0.0.1:1/", timeout=5, tag="connect-fail"
    )
    exc = result["exception"]
    if result["http_status"] != 0:
        fail("connect", f"http_status {result['http_status']}")
    if exc.get("type") != "HttpError":
        fail("connect", f"exception type {exc.get('type')}")
    if "Request error:" not in exc.get("message", ""):
        fail("connect", f"message {exc.get('message')!r}")
    print(f"PASS connect   status=0 type={exc['type']}")


async def main():
    check_version()
    server = start_server()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        await check_success(base)
        await check_http_error(base)
        await check_connect_error()
        await check_under_3s(base)
        await check_over_30s(base)
    finally:
        server.shutdown()
    print("ALL PASSED")


if __name__ == "__main__":
    asyncio.run(main())
