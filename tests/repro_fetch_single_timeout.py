"""Reproduce rusty-req v0.3.2's fetch_single timeout bug.

The server sends the response headers and a partial body immediately, then
keeps the connection open without sending the declared remaining bytes.

In v0.3.2, ``timeout=7.7`` only wraps ``builder.send()``.  Once the headers
arrive, ``res.text()`` runs outside that timeout and can wait for reqwest's
30-second client timeout instead.  A buggy build therefore takes close to 30
seconds, rather than returning after about 7.7 seconds.

Run:

    python tests/repro_fetch_single_timeout.py

The script exits with status 1 when the old behaviour is reproduced, and 0
when the request completes within the requested timeout (as a fixed build
should).  It is intentionally a diagnostic script, not a unit test: the
observed elapsed time is printed for comparison with application logs.
"""

import asyncio
import http.server
import os
import socketserver
import threading
import time

# Keep a localhost request from being routed through HTTP(S)_PROXY in the
# environment.  Set this before importing rusty_req because the Rust client
# reads proxy environment variables while it is built.
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

import rusty_req


REQUEST_TIMEOUT = 7.7
DECLARED_BODY_LENGTH = 100
SENT_BODY = b"hello"
SERVER_SLEEP = 35.0
OLD_BEHAVIOUR_THRESHOLD = 20.0


class PartialBodyHandler(http.server.BaseHTTPRequestHandler):
    """Return headers plus a truncated body, then hold the socket open."""

    def log_message(self, *_args):
        pass

    def do_POST(self):
        # Consume the request body so the test also exercises the POST path.
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length:
            self.rfile.read(content_length)

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(DECLARED_BODY_LENGTH))
        self.end_headers()

        # Headers and part of the response are available immediately.
        self.wfile.write(SENT_BODY)
        self.wfile.flush()

        # Do not send the remaining bytes.  The client must enforce its
        # timeout rather than waiting for EOF from the server.
        time.sleep(SERVER_SLEEP)


class ThreadingServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


async def run_probe(port: int) -> int:
    started = time.monotonic()
    result = await rusty_req.fetch_single(
        url=f"http://127.0.0.1:{port}/partial-body",
        method="POST",
        params={"probe": True},
        timeout=REQUEST_TIMEOUT,
        tag="fetch-single-timeout-repro",
    )
    elapsed = time.monotonic() - started

    print(f"rusty_req version: {getattr(rusty_req, '__version__', 'unknown')}")
    print(f"rusty_req module:  {getattr(rusty_req, '__file__', 'unknown')}")
    print(f"requested timeout: {REQUEST_TIMEOUT:.1f}s")
    print(f"actual elapsed:    {elapsed:.2f}s")
    print(f"http_status:       {result.get('http_status')}")
    print(f"exception:         {result.get('exception')}")
    print(f"meta:              {result.get('meta')}")
    print(f"response length:   {len(result.get('response', ''))}")

    if elapsed >= OLD_BEHAVIOUR_THRESHOLD:
        print(
            "REPRODUCED: request waited for the old ~30s client timeout "
            "instead of the requested 7.7s."
        )
        return 1

    if elapsed > REQUEST_TIMEOUT + 2.0:
        print("WARNING: request exceeded timeout by more than scheduling slack.")
        return 1

    print("NOT REPRODUCED: request completed within the requested timeout.")
    return 0


async def main() -> int:
    with ThreadingServer(("127.0.0.1", 0), PartialBodyHandler) as server:
        port = server.server_address[1]
        server_thread = threading.Thread(
            target=server.serve_forever, daemon=True
        )
        server_thread.start()
        return await run_probe(port)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
