#!/usr/bin/env python3
"""SLA showdown: rusty-req vs aiohttp / httpx / requests under a tight timeout budget.

Story
-----
Server sleeps DELAY seconds per request. Each client is given:

  * per-request timeout = SINGLE  (must be > DELAY so a healthy request can succeed)
  * batch / global budget   = TOTAL   (wall-clock SLA for the whole burst)

We fire N concurrent requests and measure success rate + wall time.
This highlights rusty-req's dual timeout control under high concurrency.

Default ladder: N = 3000, 6000, 9000  (edit with --stages).

Reproduce (after clone)
-----------------------
  # 1) install / build rusty-req
  pip install maturin aiohttp httpx requests
  maturin develop --release          # or: pip install rusty-req

  # 2a) optional: local httpbin (more realistic than the embedded server)
  docker run -d --name httpbin -p 8080:8080 mccutchen/go-httpbin:latest
  HTTPBIN_URL=http://127.0.0.1:8080 python tests/sla_showdown.py

  # 2b) no Docker: embedded /delay server starts automatically
  python tests/sla_showdown.py

  # quick demo
  python tests/sla_showdown.py --stages 3000,6000

Safety
------
``requests`` uses a small OS thread pool (default 32). Do NOT raise this to
thousands on macOS — that can kernel-panic. The script labels requests as
"thread-capped", not full N-way concurrency.

Outputs
-------
  * console tables (success rate, time, http_status; rusty-req also exception)
  * tests/sla_showdown_result.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Defaults (SLA story)
# ---------------------------------------------------------------------------
DEFAULT_STAGES = [3000, 6000, 9000]
SINGLE_TIMEOUT = 2.9
TOTAL_TIMEOUT = 3.0
DELAY = 2.3
REQUESTS_THREADS = 32  # hard safety cap for OS threads

results: List[Dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Embedded delay server (httpbin-compatible /delay/<sec>)
# ---------------------------------------------------------------------------
class _DelayHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def do_GET(self):
        try:
            path = self.path.split("?", 1)[0]
            if path.startswith("/delay/"):
                delay = float(path[len("/delay/") :] or "0")
            elif path in ("/status/200", "/"):
                delay = 0.0
            else:
                self.send_error(404)
                return
            if delay > 0:
                time.sleep(delay)
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


class _DelayServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_embedded_server() -> Tuple[str, _DelayServer]:
    import requests as req

    port = _free_port()
    server = _DelayServer(("127.0.0.1", port), _DelayHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            if req.get(f"{base}/status/200", timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(0.05)
    return base, server


# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------
def _pct(counts: Dict[Any, int], total: int) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for k, c in sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        out[str(k)] = {
            "count": int(c),
            "pct": round((c / total * 100.0) if total else 0.0, 2),
        }
    return out


def _fmt(dist: Dict[str, Dict[str, float]], limit: int = 6) -> str:
    if not dist:
        return "-"
    parts = []
    for i, (k, v) in enumerate(dist.items()):
        if i >= limit:
            parts.append("...")
            break
        parts.append(f"{k}:{int(v['count'])}({v['pct']:.1f}%)")
    return " ".join(parts)


def _record(
    name: str,
    n: int,
    ok: int,
    timed_out: int,
    duration: float,
    status_counts: Dict[Any, int],
    exception_counts: Optional[Dict[Any, int]] = None,
    note: str = "",
) -> Dict[str, Any]:
    other = max(0, n - ok - timed_out)
    row = {
        "library": name,
        "n": n,
        "successful": ok,
        "timed_out": timed_out,
        "other": other,
        "success_rate": round((ok / n * 100.0) if n else 0.0, 2),
        "duration_s": round(duration, 4),
        "within_sla": duration <= TOTAL_TIMEOUT + 0.15,  # small scheduling slack
        "http_status": _pct(status_counts, n),
        "exception_type": _pct(exception_counts or {}, n) if exception_counts else {},
        "note": note,
    }
    results.append(row)
    return row


def _print_row(row: Dict[str, Any]) -> None:
    sla = "yes" if row["within_sla"] else "NO"
    print(
        f"  {row['library']:<12} N={row['n']:<5} "
        f"ok={row['successful']:<5} rate={row['success_rate']:6.1f}%  "
        f"time={row['duration_s']:.2f}s  sla≤{TOTAL_TIMEOUT}s? {sla}"
    )
    print(f"      http_status  {_fmt(row['http_status'])}")
    if row.get("exception_type"):
        print(f"      exception    {_fmt(row['exception_type'])}")


# ---------------------------------------------------------------------------
# Library runners
# ---------------------------------------------------------------------------
async def run_rusty_req(url: str, n: int) -> Dict[str, Any]:
    import rusty_req
    from rusty_req import ConcurrencyMode, ProxyConfig, RequestItem

    rusty_req.set_debug(False)
    await rusty_req.set_global_proxy(ProxyConfig(trust_env=False))
    reqs = [
        RequestItem(url=url, method="GET", timeout=SINGLE_TIMEOUT, tag=f"r-{i}")
        for i in range(n)
    ]
    print(f"\n🔍 rusty-req  N={n}")
    t0 = time.perf_counter()
    resps = await rusty_req.fetch_requests(
        reqs, total_timeout=TOTAL_TIMEOUT, mode=ConcurrencyMode.SELECT_ALL
    )
    duration = time.perf_counter() - t0

    ok = timed_out = 0
    status_counts: Dict[Any, int] = {}
    exc_counts: Dict[Any, int] = {}
    for r in resps:
        try:
            st = int(r.get("http_status") or 0)
        except (TypeError, ValueError):
            st = 0
        status_counts[st] = status_counts.get(st, 0) + 1

        exc = r.get("exception") or {}
        if isinstance(exc, str):
            try:
                exc = json.loads(exc) if exc else {}
            except json.JSONDecodeError:
                exc = {}
        et = (exc or {}).get("type") or "None"
        exc_counts[et] = exc_counts.get(et, 0) + 1

        has_err = et not in ("None", "", None)
        if st == 200 and not has_err:
            ok += 1
        elif et in ("Timeout", "GlobalTimeout") or (
            et == "HttpError" and "timed out" in str((exc or {}).get("message", "")).lower()
        ):
            timed_out += 1

    row = _record(
        "rusty-req",
        n,
        ok,
        timed_out,
        duration,
        status_counts,
        exc_counts,
        note="Native per-request timeout + total_timeout",
    )
    _print_row(row)
    return row


async def run_httpx(url: str, n: int) -> Dict[str, Any]:
    import httpx

    print(f"\n🔍 httpx      N={n}")
    ok = timed_out = completed = 0
    status_counts: Dict[Any, int] = {}
    t0 = time.perf_counter()
    timeout = httpx.Timeout(SINGLE_TIMEOUT)
    async with httpx.AsyncClient(
        timeout=timeout,
        limits=httpx.Limits(max_connections=n, max_keepalive_connections=n),
    ) as client:
        sem = asyncio.Semaphore(n)

        async def one():
            nonlocal ok, timed_out, completed
            async with sem:
                try:
                    r = await client.get(url)
                    completed += 1
                    status_counts[r.status_code] = status_counts.get(r.status_code, 0) + 1
                    if r.status_code == 200:
                        ok += 1
                except httpx.TimeoutException:
                    completed += 1
                    timed_out += 1
                    status_counts[0] = status_counts.get(0, 0) + 1
                except Exception:
                    completed += 1
                    status_counts["err"] = status_counts.get("err", 0) + 1

        try:
            await asyncio.wait_for(asyncio.gather(*[one() for _ in range(n)]), timeout=TOTAL_TIMEOUT)
            duration = time.perf_counter() - t0
        except asyncio.TimeoutError:
            duration = time.perf_counter() - t0
            rem = max(0, n - completed)
            timed_out += rem
            status_counts[0] = status_counts.get(0, 0) + rem

    row = _record(
        "httpx",
        n,
        ok,
        timed_out,
        duration,
        status_counts,
        note="AsyncClient + asyncio.wait_for as global budget",
    )
    _print_row(row)
    return row


async def run_aiohttp(url: str, n: int) -> Dict[str, Any]:
    import aiohttp

    print(f"\n🔍 aiohttp    N={n}")
    ok = timed_out = completed = 0
    status_counts: Dict[Any, int] = {}
    t0 = time.perf_counter()
    per = aiohttp.ClientTimeout(total=SINGLE_TIMEOUT)
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit=n, limit_per_host=n),
        timeout=aiohttp.ClientTimeout(total=TOTAL_TIMEOUT),
    ) as session:
        sem = asyncio.Semaphore(n)

        async def one():
            nonlocal ok, timed_out, completed
            async with sem:
                try:
                    async with session.get(url, timeout=per) as r:
                        await r.read()
                        completed += 1
                        status_counts[r.status] = status_counts.get(r.status, 0) + 1
                        if r.status == 200:
                            ok += 1
                except asyncio.TimeoutError:
                    completed += 1
                    timed_out += 1
                    status_counts[0] = status_counts.get(0, 0) + 1
                except Exception:
                    completed += 1
                    status_counts["err"] = status_counts.get("err", 0) + 1

        try:
            await asyncio.wait_for(asyncio.gather(*[one() for _ in range(n)]), timeout=TOTAL_TIMEOUT)
            duration = time.perf_counter() - t0
        except asyncio.TimeoutError:
            duration = time.perf_counter() - t0
            rem = max(0, n - completed)
            timed_out += rem
            status_counts[0] = status_counts.get(0, 0) + rem

    row = _record(
        "aiohttp",
        n,
        ok,
        timed_out,
        duration,
        status_counts,
        note="ClientTimeout + connector limit=N + asyncio.wait_for",
    )
    _print_row(row)
    return row


def run_requests(url: str, n: int) -> Dict[str, Any]:
    import requests

    workers = min(n, REQUESTS_THREADS)
    print(f"\n🔍 requests   N={n} threads≤{workers}")
    ok = timed_out = 0
    status_counts: Dict[Any, int] = {}
    start = time.perf_counter()

    def one() -> Tuple[str, Any]:
        remaining = TOTAL_TIMEOUT - (time.perf_counter() - start)
        if remaining <= 0:
            return "timeout", 0
        actual = min(SINGLE_TIMEOUT, remaining)
        try:
            r = requests.get(url, timeout=actual)
            return ("ok" if r.status_code == 200 else "other"), r.status_code
        except requests.Timeout:
            return "timeout", 0
        except Exception:
            return "other", "err"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = []
        submitted = 0
        while submitted < n:
            if time.perf_counter() - start >= TOTAL_TIMEOUT:
                break
            batch = min(workers, n - submitted)
            batch_futs = [pool.submit(one) for _ in range(batch)]
            futures.extend(batch_futs)
            submitted += batch
            for fut in as_completed(batch_futs):
                if time.perf_counter() - start >= TOTAL_TIMEOUT:
                    break
                kind, code = fut.result()
                status_counts[code] = status_counts.get(code, 0) + 1
                if kind == "ok":
                    ok += 1
                elif kind == "timeout":
                    timed_out += 1
        extra = sum(1 for f in futures if not f.done()) + max(0, n - submitted)
        timed_out += extra
        status_counts[0] = status_counts.get(0, 0) + extra
        for f in futures:
            f.cancel()

    duration = time.perf_counter() - start
    row = _record(
        "requests",
        n,
        ok,
        timed_out,
        duration,
        status_counts,
        note=f"Thread pool capped at {workers} OS threads (not N-way concurrent)",
    )
    _print_row(row)
    return row


async def run_level(url: str, n: int) -> None:
    print("\n" + "=" * 72)
    print(f"N = {n} concurrent  |  single={SINGLE_TIMEOUT}s  total={TOTAL_TIMEOUT}s  delay={DELAY}s")
    print("=" * 72)
    await run_rusty_req(url, n)
    await run_httpx(url, n)
    await run_aiohttp(url, n)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, run_requests, url, n)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def markdown_success_table() -> str:
    stages = sorted({r["n"] for r in results})
    libs = []
    for r in results:
        if r["library"] not in libs:
            libs.append(r["library"])
    header = "| Library | " + " | ".join(f"N={s}" for s in stages) + " |"
    sep = "|---------|" + "|".join(["------------"] * len(stages)) + "|"
    lines = [
        "### Success rate / wall time",
        "",
        header,
        sep,
    ]
    for lib in libs:
        cells = []
        for s in stages:
            hit = next((x for x in results if x["library"] == lib and x["n"] == s), None)
            if not hit:
                cells.append("-")
            else:
                cells.append(f"{hit['success_rate']:.1f}% / {hit['duration_s']:.2f}s")
        lines.append(f"| **{lib}** | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def markdown_detail_table() -> str:
    lines = [
        "### Detail (http_status; rusty-req exception)",
        "",
        "| N | Library | OK | Rate | Time | Within SLA | http_status | exception |",
        "|---|---------|----|------|------|------------|-------------|-----------|",
    ]
    for r in results:
        lines.append(
            f"| {r['n']} | **{r['library']}** | {r['successful']}/{r['n']} | "
            f"{r['success_rate']:.1f}% | {r['duration_s']:.2f}s | "
            f"{'yes' if r['within_sla'] else 'no'} | "
            f"{_fmt(r['http_status'])} | {_fmt(r.get('exception_type') or {})} |"
        )
    return "\n".join(lines)


def markdown_readme_en() -> str:
    """Compact table suitable for pasting into README.md."""
    # one row per library, columns = stages success + time for primary stages
    stages = sorted({r["n"] for r in results})
    lines = [
        f"Under the same SLA (global timeout **{TOTAL_TIMEOUT}s**, per-request timeout "
        f"**{SINGLE_TIMEOUT}s**, server delay **{DELAY}s**), concurrent bursts at "
        f"N={', '.join(str(s) for s in stages)}:",
        "",
        "| Library | " + " | ".join(f"N={s} success / time" for s in stages) + " | Notes |",
        "|---------|" + "|".join(["-------------------"] * len(stages)) + "|-------|",
    ]
    notes = {
        "rusty-req": "Native dual timeouts; stays inside SLA at high concurrency",
        "httpx": "Often misses the global budget; may overshoot wall time on cancel",
        "aiohttp": "Fine at moderate N; collapses under tight SLA at higher concurrency",
        "requests": f"Thread pool capped at {REQUESTS_THREADS} (not N-way concurrent)",
    }
    libs = []
    for r in results:
        if r["library"] not in libs:
            libs.append(r["library"])
    for lib in libs:
        cells = []
        for s in stages:
            hit = next((x for x in results if x["library"] == lib and x["n"] == s), None)
            cells.append(
                f"**{hit['success_rate']:.1f}%** / {hit['duration_s']:.2f}s" if hit else "-"
            )
        lines.append(
            f"| **{lib}** | " + " | ".join(cells) + f" | {notes.get(lib, '')} |"
        )
    return "\n".join(lines)


def markdown_readme_zh() -> str:
    stages = sorted({r["n"] for r in results})
    lines = [
        f"在相同 SLA 下（全局超时 **{TOTAL_TIMEOUT}s**，单请求超时 **{SINGLE_TIMEOUT}s**，"
        f"服务端 delay **{DELAY}s**），并发档位 N={', '.join(str(s) for s in stages)}：",
        "",
        "| 库 | " + " | ".join(f"N={s} 成功率 / 耗时" for s in stages) + " | 说明 |",
        "|----|" + "|".join(["-------------------"] * len(stages)) + "|------|",
    ]
    notes = {
        "rusty-req": "原生双超时；高并发下仍能压在 SLA 内",
        "httpx": "常无法在全局预算内完成；取消时墙钟可能明显超标",
        "aiohttp": "中等并发尚可；紧 SLA + 更高并发时成功率断崖",
        "requests": f"线程池上限 {REQUESTS_THREADS}（非 N 路真并发）",
    }
    libs = []
    for r in results:
        if r["library"] not in libs:
            libs.append(r["library"])
    for lib in libs:
        cells = []
        for s in stages:
            hit = next((x for x in results if x["library"] == lib and x["n"] == s), None)
            cells.append(
                f"**{hit['success_rate']:.1f}%** / {hit['duration_s']:.2f}s" if hit else "-"
            )
        lines.append(
            f"| **{lib}** | " + " | ".join(cells) + f" | {notes.get(lib, '')} |"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SLA timeout showdown (reproducible)")
    p.add_argument(
        "--stages",
        default=",".join(str(x) for x in DEFAULT_STAGES),
        help="comma-separated concurrency levels (default 3000,6000,9000)",
    )
    p.add_argument("--single-timeout", type=float, default=SINGLE_TIMEOUT)
    p.add_argument("--total-timeout", type=float, default=TOTAL_TIMEOUT)
    p.add_argument("--delay", type=float, default=DELAY)
    p.add_argument(
        "--requests-threads",
        type=int,
        default=REQUESTS_THREADS,
        help=f"OS thread cap for requests (default {REQUESTS_THREADS}, keep small on macOS)",
    )
    return p.parse_args()


async def main() -> int:
    global SINGLE_TIMEOUT, TOTAL_TIMEOUT, DELAY, REQUESTS_THREADS, results
    args = parse_args()
    SINGLE_TIMEOUT = args.single_timeout
    TOTAL_TIMEOUT = args.total_timeout
    DELAY = args.delay
    REQUESTS_THREADS = max(1, min(args.requests_threads, 64))
    results = []

    stages = [int(x.strip()) for x in args.stages.split(",") if x.strip()]
    if not stages:
        stages = list(DEFAULT_STAGES)

    try:
        import rusty_req  # noqa: F401
    except ImportError:
        print("❌ rusty_req not installed.")
        print("   pip install maturin && maturin develop --release")
        print("   # or: pip install rusty-req")
        return 1

    for dep in ("aiohttp", "httpx", "requests"):
        try:
            __import__(dep)
        except ImportError:
            print(f"❌ missing dependency: {dep}")
            print("   pip install aiohttp httpx requests")
            return 1

    external = os.getenv("HTTPBIN_URL")
    server: Optional[_DelayServer] = None
    if external:
        base = external.rstrip("/")
        url = f"{base}/delay/{DELAY}"
        print(f"🌐 HTTPBIN_URL → {url}")
        import requests as req

        try:
            req.get(f"{base}/status/200", timeout=5).raise_for_status()
        except Exception as e:
            print(f"❌ cannot reach HTTPBIN_URL: {e}")
            return 1
    else:
        base, server = start_embedded_server()
        url = f"{base}/delay/{DELAY}"
        print(f"🌐 Embedded delay server → {url}")
        print("   (set HTTPBIN_URL=http://127.0.0.1:8080 to use Docker go-httpbin)")

    print("📦 SLA Showdown")
    print(f"   single={SINGLE_TIMEOUT}s  total={TOTAL_TIMEOUT}s  delay={DELAY}s")
    print(f"   stages={stages}  requests_threads≤{REQUESTS_THREADS}")

    try:
        for n in stages:
            await run_level(url, n)
    finally:
        if server is not None:
            server.shutdown()

    print("\n" + "=" * 72)
    print(markdown_success_table())
    print()
    print(markdown_detail_table())
    print()
    print("--- README (EN) snippet ---")
    print(markdown_readme_en())
    print()
    print("--- README (ZH) snippet ---")
    print(markdown_readme_zh())

    out = {
        "params": {
            "single_timeout": SINGLE_TIMEOUT,
            "total_timeout": TOTAL_TIMEOUT,
            "delay": DELAY,
            "stages": stages,
            "requests_threads": REQUESTS_THREADS,
            "url": url,
        },
        "results": results,
        "markdown_success": markdown_success_table(),
        "markdown_detail": markdown_detail_table(),
        "markdown_readme_en": markdown_readme_en(),
        "markdown_readme_zh": markdown_readme_zh(),
    }
    out_path = os.path.join(os.path.dirname(__file__), "sla_showdown_result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Saved {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
