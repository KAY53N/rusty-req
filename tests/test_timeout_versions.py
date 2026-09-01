"""Cross-version timeout tests for ``fetch_single`` and ``fetch_requests``.

Run this file once in a ``rusty-req==0.3.2`` environment and once in the
latest-version environment.  The local server sends response headers and a
partial body immediately, then leaves the response incomplete.  This is the
case that exposed the old ``fetch_single`` implementation waiting for the
30-second reqwest client timeout.

The tests intentionally use ``unittest`` and ``asyncio.run`` so that the only
package required in each environment is rusty-req itself.  They assert the
desired contract in every environment; failures identify the version/API
combination that still has a timeout defect.
"""

import asyncio
import http.server
import importlib.metadata
import os
import socketserver
import threading
import time
import unittest

# Avoid routing localhost through a user's HTTP(S) proxy.
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

import rusty_req


REQUEST_TIMEOUT = 7.7
BODY_LENGTH = 100
BODY_PREFIX = b"hello"
SERVER_SLEEP = 35.0
# Allow startup/scheduling overhead, but distinguish 7.7s from the old 30s.
MAX_EXPECTED_FIXED_SECONDS = REQUEST_TIMEOUT + 3.0


class _PartialBodyHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length:
            self.rfile.read(content_length)

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(BODY_LENGTH))
        self.end_headers()
        self.wfile.write(BODY_PREFIX)
        self.wfile.flush()

        # Keep the declared response incomplete.  The client must enforce its
        # timeout while reading the body instead of waiting for EOF.
        time.sleep(SERVER_SLEEP)


class _ThreadingServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _installed_version() -> str:
    try:
        return importlib.metadata.version("rusty-req")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


class TimeoutBehaviourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = _ThreadingServer(("127.0.0.1", 0), _PartialBodyHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.version = _installed_version()
        print(f"\nTesting rusty-req {cls.version} ({rusty_req.__file__})")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _url(self) -> str:
        return f"http://127.0.0.1:{self.port}/partial-body"

    def test_fetch_single_timeout(self):
        """A single request must not wait past its 7.7s timeout."""

        async def request():
            return await rusty_req.fetch_single(
                self._url(),
                method="POST",
                params={"probe": True},
                timeout=REQUEST_TIMEOUT,
                tag="single-timeout-test",
            )

        started = time.monotonic()
        result = asyncio.run(request())
        elapsed = time.monotonic() - started
        print(
            f"fetch_single:   {elapsed:.2f}s, status={result.get('http_status')}, "
            f"exception={result.get('exception')}"
        )

        self.assertLess(
            elapsed,
            MAX_EXPECTED_FIXED_SECONDS,
            "fetch_single exceeded the requested timeout (the old v0.3.2 "
            "implementation is expected to fail here after ~30s)",
        )

    def test_fetch_requests_total_timeout(self):
        """The batch-level 7.7s timeout must cancel a pending request."""

        request_item = rusty_req.RequestItem(
            self._url(),
            method="POST",
            params={"probe": True},
            # Keep the per-request timer out of the way; test total_timeout.
            timeout=30.0,
            tag="batch-timeout-test",
        )

        async def request():
            return await rusty_req.fetch_requests(
                [request_item], total_timeout=REQUEST_TIMEOUT
            )

        started = time.monotonic()
        error = None
        results = None
        try:
            results = asyncio.run(request())
        except BaseException as exc:  # RustPanic is surfaced by pyo3_asyncio.
            error = exc
        elapsed = time.monotonic() - started
        if results:
            result = results[0]
            status = result.get("http_status")
            exception = result.get("exception")
        else:
            status = "<no result>"
            exception = repr(error)
        print(
            f"fetch_requests: {elapsed:.2f}s, status={status}, "
            f"exception={exception}"
        )

        self.assertIsNone(
            error,
            "fetch_requests raised instead of returning a timeout result",
        )
        self.assertLess(
            elapsed,
            MAX_EXPECTED_FIXED_SECONDS,
            "fetch_requests exceeded its total_timeout",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
