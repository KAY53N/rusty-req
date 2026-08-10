"""Regression test: a per-request `timeout` must be honoured as given.

`execute_single_request` used to clamp the caller's value with `.max(3.0)`, so
every timeout below three seconds was silently raised to three seconds — a
`timeout=0.5` request kept waiting for 3s. That is invisible from Python: the
call still "works", it just takes up to 6x longer than asked, which defeats
fail-fast health checks and any caller with a latency budget under 3s.

Run:  python tests/test_timeout_honoured.py
Exits non-zero if any timeout is overshot.
"""
import asyncio
import http.server
import socketserver
import threading
import time

import rusty_req

PORT = 8733
SLACK = 0.75  # generous allowance for scheduling + client setup


class _Handler(http.server.BaseHTTPRequestHandler):
    """GET /<seconds> sleeps that long, then returns 200 {}."""

    def log_message(self, *args):
        pass

    def do_GET(self):
        try:
            time.sleep(float(self.path.strip("/") or 0))
            body = b"{}"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client timed out and hung up - that is the point of the test


class _Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


async def main() -> int:
    server = _Server(("127.0.0.1", PORT), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # (per-request timeout, server delay). Each timeout is well under the old
    # 3s floor, so the pre-fix build overshoots every one of them.
    cases = [(0.5, 5.0), (1.0, 5.0), (2.0, 5.0)]
    failures = []

    try:
        for timeout, delay in cases:
            started = time.monotonic()
            await rusty_req.fetch_single(
                f"http://127.0.0.1:{PORT}/{delay}", "GET", timeout=timeout
            )
            elapsed = time.monotonic() - started

            if elapsed > timeout + SLACK:
                failures.append(
                    f"timeout={timeout}s overshot: returned after {elapsed:.2f}s"
                )
                print(f"FAIL  timeout={timeout:<4} returned after {elapsed:.2f}s")
            else:
                print(f"ok    timeout={timeout:<4} returned after {elapsed:.2f}s")

        # A request that finishes inside its budget must NOT be cut short.
        started = time.monotonic()
        result = await rusty_req.fetch_single(
            f"http://127.0.0.1:{PORT}/1.0", "GET", timeout=5.0
        )
        elapsed = time.monotonic() - started
        status = int(result["http_status"])
        if status != 200:
            failures.append(f"fast request was cut short: http_status={status}")
            print(f"FAIL  fast request returned {status} after {elapsed:.2f}s")
        else:
            print(f"ok    fast request returned 200 after {elapsed:.2f}s")
    finally:
        server.shutdown()

    if failures:
        print("\n" + "\n".join(failures))
        return 1
    print("\nall timeouts honoured")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
