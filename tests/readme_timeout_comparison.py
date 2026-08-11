"""Timeout performance comparison: direct burst + staged ramp.

Two load modes (run separately / sequentially — never interleaved):

  direct  — one burst of N concurrent requests
  staged  — ladder of sizes, one level at a time (safer for finding a ceiling)

How to push volume WITHOUT kernel-panicing macOS
------------------------------------------------
The previous crash was ~2000 *OS threads* from `requests` ThreadPoolExecutor,
not "N is big" by itself. Safe high volume means:

  1. Cap *inflight* (connections / threads), not necessarily total N.
  2. Prefer async libs (rusty-req / aiohttp / httpx) for high N.
  3. Keep requests threads ≤ 32–64 always (1 request ≠ 1 thread forever is OK
     only if the pool is small and work is queued).
  4. Ramp staged: 200 → 500 → 1000 → 2000; stop when success rate or machine
     load degrades — do not jump straight to 5000.
  5. At N≥1000, skip requests or use --libs rusty-req,aiohttp,httpx.

Suggested profiles (Apple Silicon laptop):

  # Safe README-style (default)
  --mode direct --n 1000 --max-threads 32 --max-connections 500

  # Higher async volume (skip thread-per-request library)
  --mode staged --stages 500,1000,2000,3000 \\
    --libs rusty-req,aiohttp,httpx --max-connections 800

  # Direct high N async only
  --mode direct --n 3000 --libs rusty-req,aiohttp,httpx --max-connections 800

NEVER: --n 5000 with requests uncapped threads / --force casually.

Usage:
  HTTPBIN_URL=http://127.0.0.1:8080 python tests/readme_timeout_comparison.py
  python tests/readme_timeout_comparison.py --mode direct --n 1000
  python tests/readme_timeout_comparison.py --mode staged --stages 200,500,1000
  python tests/readme_timeout_comparison.py --libs rusty-req,aiohttp --n 2000
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
from typing import Any, Dict, List, Optional, Sequence, Tuple

import aiohttp
import httpx
import requests

# --- defaults (conservative after kernel panic) ------------------------------
DEFAULT_N = 1000
DEFAULT_STAGES = [200, 500, 1000, 2000]
# Burst size ceiling without --force (async + socket pressure still hurts)
HARD_N_CAP = 5000
# requests uses real OS threads — this is what panics macOS if too high
DEFAULT_MAX_THREADS = 32
HARD_THREAD_CAP = 64
# async clients: bound concurrent sockets even if N is larger (queue the rest)
DEFAULT_MAX_CONNECTIONS = 500
HARD_CONN_CAP = 1000
# Above this N, skip requests unless user explicitly includes it via --libs
REQUESTS_AUTO_SKIP_N = 1000

ALL_LIBS = ("rusty-req", "httpx", "aiohttp", "requests")
DEFAULT_LIBS = ",".join(ALL_LIBS)

SINGLE_TIMEOUT = 2.9
TOTAL_TIMEOUT = 3.0
DELAY = 2.3
COOLDOWN_SECS = 0.0  # no inter-lib / inter-stage cooldown

# filled per run
results: List[Dict[str, Any]] = []
MAX_THREADS = DEFAULT_MAX_THREADS
MAX_CONNECTIONS = DEFAULT_MAX_CONNECTIONS
ENABLED_LIBS: Sequence[str] = ALL_LIBS


# --- Embedded /delay/<seconds> server ----------------------------------------
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
            body = b'{"ok": true}'
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
    port = _free_port()
    server = _DelayServer(("127.0.0.1", port), _DelayHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            r = requests.get(f"{base}/status/200", timeout=1)
            if r.status_code == 200:
                break
        except Exception:
            time.sleep(0.05)
    return base, server


def classify_ok(http_status: Any, exception: Any) -> bool:
    try:
        status = int(http_status) if http_status not in (None, "") else 0
    except (TypeError, ValueError):
        status = 0
    if isinstance(exception, str):
        try:
            exception = json.loads(exception) if exception else {}
        except json.JSONDecodeError:
            exception = {"type": "ParseError"}
    if not isinstance(exception, dict):
        exception = {}
    has_err = exception.get("type") not in (None, "", "None")
    return status == 200 and not has_err


def _pct_map(counts: Dict[Any, int], total: int) -> Dict[str, Dict[str, float]]:
    """Return {key: {count, pct}} sorted by count desc."""
    out: Dict[str, Dict[str, float]] = {}
    for k, c in sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        key = str(k)
        out[key] = {
            "count": c,
            "pct": round((c / total * 100.0) if total else 0.0, 2),
        }
    return out


def _fmt_dist(dist: Dict[str, Dict[str, float]], limit: int = 8) -> str:
    if not dist:
        return "-"
    parts = []
    for i, (k, v) in enumerate(dist.items()):
        if i >= limit:
            parts.append("...")
            break
        parts.append(f"{k}:{int(v['count'])}({v['pct']:.1f}%)")
    return " ".join(parts)


def record(
    name: str,
    mode: str,
    total: int,
    successful: int,
    timed_out: int,
    duration: float,
    note: str = "",
    status_counts: Optional[Dict[Any, int]] = None,
    exception_counts: Optional[Dict[Any, int]] = None,
) -> Dict[str, Any]:
    failed_other = max(0, total - successful - timed_out)
    status_dist = _pct_map(status_counts or {}, total)
    exception_dist = _pct_map(exception_counts or {}, total)
    row = {
        "name": name,
        "mode": mode,
        "total": total,
        "successful": successful,
        "timed_out": timed_out,
        "failed_other": failed_other,
        "success_rate": (successful / total * 100.0) if total else 0.0,
        "duration": duration,
        "note": note,
        "http_status": status_dist,
        "exception_type": exception_dist,
    }
    results.append(row)
    return row


def print_row(r: Dict[str, Any]) -> None:
    print(
        f"  [{r['mode']:<12}] {r['name']:<12} "
        f"N={r['total']:<5} ok={r['successful']:<5} "
        f"timeout={r['timed_out']:<5} other={r['failed_other']:<5} "
        f"rate={r['success_rate']:6.1f}%  time={r['duration']:.2f}s"
    )
    print(f"      http_status  {_fmt_dist(r.get('http_status') or {})}")
    if r.get("exception_type"):
        print(f"      exception    {_fmt_dist(r.get('exception_type') or {})}")


def _note_for(name: str, successful: int, total: int, duration: float, timed_out: int) -> str:
    rate = (successful / total * 100.0) if total else 0.0
    if name == "Rusty-req":
        return "Native per-request + total_timeout"
    if name == "httpx":
        if rate < 50 or duration > TOTAL_TIMEOUT * 2:
            return "Batch often misses tight global budget under high concurrency"
        return "Async HTTP client (global via asyncio.wait_for)"
    if name == "aiohttp":
        if timed_out > 0:
            return "Some timeouts under this load"
        return "Async HTTP client (connector limit raised)"
    if name == "requests":
        return "Thread-pool sync; approximate global budget"
    return ""


# --- Library runners (always direct burst of `n` concurrent) -----------------
async def run_rusty_req(url: str, n: int, mode: str) -> Dict[str, Any]:
    import rusty_req
    from rusty_req import ConcurrencyMode, ProxyConfig, RequestItem

    rusty_req.set_debug(False)
    await rusty_req.set_global_proxy(ProxyConfig(trust_env=False))
    reqs = [
        RequestItem(url=url, method="GET", timeout=SINGLE_TIMEOUT, tag=f"rr-{i}")
        for i in range(n)
    ]
    print(f"\n🔍 rusty-req  mode={mode} N={n} single={SINGLE_TIMEOUT} total={TOTAL_TIMEOUT}")
    t0 = time.perf_counter()
    resps = await rusty_req.fetch_requests(
        reqs, total_timeout=TOTAL_TIMEOUT, mode=ConcurrencyMode.SELECT_ALL
    )
    duration = time.perf_counter() - t0

    successful = 0
    timed_out = 0
    status_counts: Dict[Any, int] = {}
    exception_counts: Dict[Any, int] = {}
    for r in resps:
        try:
            st = int(r.get("http_status") or 0)
        except (TypeError, ValueError):
            st = 0
        status_counts[st] = status_counts.get(st, 0) + 1

        exc = r.get("exception", {})
        if isinstance(exc, str):
            try:
                exc = json.loads(exc) if exc else {}
            except json.JSONDecodeError:
                exc = {}
        etype = (exc or {}).get("type") or "None"
        exception_counts[etype] = exception_counts.get(etype, 0) + 1

        if classify_ok(r.get("http_status"), exc):
            successful += 1
        elif etype in ("Timeout", "GlobalTimeout") or (
            etype == "HttpError"
            and "timed out" in str((exc or {}).get("message", "")).lower()
        ):
            timed_out += 1

    row = record(
        "Rusty-req",
        mode,
        n,
        successful,
        timed_out,
        duration,
        note=_note_for("Rusty-req", successful, n, duration, timed_out),
        status_counts=status_counts,
        exception_counts=exception_counts,
    )
    print_row(row)
    return row


async def run_httpx(url: str, n: int, mode: str) -> Dict[str, Any]:
    conn_cap = min(n, MAX_CONNECTIONS)
    print(
        f"\n🔍 httpx      mode={mode} N={n} inflight≤{conn_cap} "
        f"single={SINGLE_TIMEOUT} total={TOTAL_TIMEOUT}"
    )
    t0 = time.perf_counter()
    successful = 0
    timed_out = 0
    completed = 0
    status_counts: Dict[Any, int] = {}
    timeout = httpx.Timeout(SINGLE_TIMEOUT)
    async with httpx.AsyncClient(
        timeout=timeout,
        limits=httpx.Limits(
            max_connections=conn_cap, max_keepalive_connections=conn_cap
        ),
    ) as client:
        sem = asyncio.Semaphore(conn_cap)

        async def one():
            nonlocal successful, timed_out, completed
            async with sem:
                try:
                    r = await client.get(url)
                    completed += 1
                    status_counts[r.status_code] = status_counts.get(r.status_code, 0) + 1
                    if r.status_code == 200:
                        successful += 1
                except httpx.TimeoutException:
                    completed += 1
                    timed_out += 1
                    status_counts[0] = status_counts.get(0, 0) + 1
                except Exception:
                    completed += 1
                    status_counts["err"] = status_counts.get("err", 0) + 1

        try:
            await asyncio.wait_for(
                asyncio.gather(*[one() for _ in range(n)]),
                timeout=TOTAL_TIMEOUT,
            )
            duration = time.perf_counter() - t0
        except asyncio.TimeoutError:
            duration = time.perf_counter() - t0
            remaining = max(0, n - completed)
            timed_out += remaining
            status_counts[0] = status_counts.get(0, 0) + remaining

    row = record(
        "httpx",
        mode,
        n,
        successful,
        timed_out,
        duration,
        note=_note_for("httpx", successful, n, duration, timed_out),
        status_counts=status_counts,
    )
    print_row(row)
    return row


async def run_aiohttp(url: str, n: int, mode: str) -> Dict[str, Any]:
    conn_cap = min(n, MAX_CONNECTIONS)
    print(
        f"\n🔍 aiohttp    mode={mode} N={n} inflight≤{conn_cap} "
        f"single={SINGLE_TIMEOUT} total={TOTAL_TIMEOUT}"
    )
    t0 = time.perf_counter()
    successful = 0
    timed_out = 0
    completed = 0
    status_counts: Dict[Any, int] = {}
    per_req_timeout = aiohttp.ClientTimeout(total=SINGLE_TIMEOUT)
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit=conn_cap, limit_per_host=conn_cap),
        timeout=aiohttp.ClientTimeout(total=TOTAL_TIMEOUT),
    ) as session:
        sem = asyncio.Semaphore(conn_cap)

        async def one():
            nonlocal successful, timed_out, completed
            async with sem:
                try:
                    async with session.get(url, timeout=per_req_timeout) as r:
                        await r.read()
                        completed += 1
                        status_counts[r.status] = status_counts.get(r.status, 0) + 1
                        if r.status == 200:
                            successful += 1
                except asyncio.TimeoutError:
                    completed += 1
                    timed_out += 1
                    status_counts[0] = status_counts.get(0, 0) + 1
                except Exception:
                    completed += 1
                    status_counts["err"] = status_counts.get("err", 0) + 1

        try:
            await asyncio.wait_for(
                asyncio.gather(*[one() for _ in range(n)]),
                timeout=TOTAL_TIMEOUT,
            )
            duration = time.perf_counter() - t0
        except asyncio.TimeoutError:
            duration = time.perf_counter() - t0
            remaining = max(0, n - completed)
            timed_out += remaining
            status_counts[0] = status_counts.get(0, 0) + remaining

    row = record(
        "aiohttp",
        mode,
        n,
        successful,
        timed_out,
        duration,
        note=_note_for("aiohttp", successful, n, duration, timed_out),
        status_counts=status_counts,
    )
    print_row(row)
    return row


def run_requests(url: str, n: int, mode: str) -> Dict[str, Any]:
    # CRITICAL: each worker is a real OS thread. macOS panicked at ~2015 threads
    # (spinlock timeout in com.apple.kec.pthread). Keep this tiny.
    workers = max(1, min(n, MAX_THREADS, HARD_THREAD_CAP))
    print(
        f"\n🔍 requests   mode={mode} N={n} threads≤{workers} "
        f"single={SINGLE_TIMEOUT} total={TOTAL_TIMEOUT}"
    )
    successful = 0
    timed_out = 0
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
        # Submit in waves matching worker count so we never queue huge futures.
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
                    successful += 1
                elif kind == "timeout":
                    timed_out += 1
        unfinished = sum(1 for f in futures if not f.done())
        not_submitted = max(0, n - submitted)
        extra = unfinished + not_submitted
        timed_out += extra
        status_counts[0] = status_counts.get(0, 0) + extra
        for f in futures:
            f.cancel()

    duration = time.perf_counter() - start
    row = record(
        "requests",
        mode,
        n,
        successful,
        timed_out,
        duration,
        note=_note_for("requests", successful, n, duration, timed_out)
        + f" (threads≤{workers})",
        status_counts=status_counts,
    )
    print_row(row)
    return row


async def run_all_libs(url: str, n: int, mode: str) -> None:
    """One concurrent burst of size n for every enabled library."""
    libs = list(ENABLED_LIBS)
    # Safety: at high N, never let requests spawn a huge thread storm by accident.
    if "requests" in libs and n >= REQUESTS_AUTO_SKIP_N and MAX_THREADS > HARD_THREAD_CAP:
        print(
            f"⚠️  skipping requests at N={n}: max_threads={MAX_THREADS} too high "
            f"(hard cap {HARD_THREAD_CAP})"
        )
        libs = [x for x in libs if x != "requests"]
    if "requests" in libs and n >= REQUESTS_AUTO_SKIP_N:
        print(
            f"ℹ️  N={n}≥{REQUESTS_AUTO_SKIP_N}: requests will run with only "
            f"{min(MAX_THREADS, HARD_THREAD_CAP)} OS threads (queued, not 1:1). "
            f"For high-volume fairness prefer --libs rusty-req,aiohttp,httpx"
        )

    runners = {
        "rusty-req": lambda: run_rusty_req(url, n, mode),
        "httpx": lambda: run_httpx(url, n, mode),
        "aiohttp": lambda: run_aiohttp(url, n, mode),
        "requests": None,  # sync; handled below
    }
    first = True
    for name in libs:
        if not first:
            await asyncio.sleep(COOLDOWN_SECS)
        first = False
        if name == "requests":
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, run_requests, url, n, mode)
        else:
            await runners[name]()


async def run_direct(url: str, n: int) -> None:
    """Mode A: direct full concurrency — all N at once."""
    print("\n" + "=" * 80)
    print(f"MODE: direct  (fire all {n} requests at once)")
    print("=" * 80)
    await run_all_libs(url, n, mode=f"direct")


async def run_staged(url: str, stages: List[int]) -> None:
    """Mode B: staged ramp — ladder of concurrent sizes, each level is a full burst."""
    print("\n" + "=" * 80)
    print(f"MODE: staged  (ramp levels: {stages})")
    print("=" * 80)
    for i, n in enumerate(stages, 1):
        print(f"\n----- stage {i}/{len(stages)}: concurrent N={n} -----")
        await run_all_libs(url, n, mode=f"stage{i}@{n}")
        if i < len(stages):
            print(f"⏳ stage cooldown {COOLDOWN_SECS}s...")
            await asyncio.sleep(COOLDOWN_SECS)


def markdown_table(mode_filter: Optional[str] = None) -> str:
    rows = results
    if mode_filter == "direct":
        rows = [r for r in results if r["mode"] == "direct"]
    elif mode_filter == "staged":
        rows = [r for r in results if r["mode"].startswith("stage")]

    lines = [
        "| Mode | Library | N | OK | Timeout | Rate | Time | http_status 占比 | exception 占比 |",
        "|------|---------|---|----|---------|------|------|------------------|----------------|",
    ]
    for r in rows:
        lines.append(
            f"| {r['mode']} | **{r['name']}** | {r['total']} | {r['successful']} | "
            f"{r['timed_out']} | {r['success_rate']:.1f}% | {r['duration']:.2f}s | "
            f"{_fmt_dist(r.get('http_status') or {})} | "
            f"{_fmt_dist(r.get('exception_type') or {})} |"
        )
    return "\n".join(lines)


def summary_pivot() -> str:
    """Compact pivot: library × N for staged + direct row."""
    # collect all (mode, n) keys in order
    keys: List[Tuple[str, int]] = []
    seen = set()
    for r in results:
        k = (r["mode"], r["total"])
        if k not in seen:
            seen.add(k)
            keys.append(k)

    libs = []
    for r in results:
        if r["name"] not in libs:
            libs.append(r["name"])

    header = "| Library | " + " | ".join(f"{m} N={n}" for m, n in keys) + " |"
    sep = "|---------|" + "|".join(["------------"] * len(keys)) + "|"
    lines = [header, sep]
    for lib in libs:
        cells = []
        for m, n in keys:
            hit = next(
                (x for x in results if x["name"] == lib and x["mode"] == m and x["total"] == n),
                None,
            )
            if hit is None:
                cells.append("-")
            else:
                cells.append(f"{hit['success_rate']:.0f}%/{hit['duration']:.2f}s")
        lines.append(f"| **{lib}** | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Timeout comparison: direct + staged load (safe caps for macOS)"
    )
    p.add_argument(
        "--mode",
        choices=("all", "direct", "staged"),
        default=os.getenv("BENCH_MODE", "all"),
        help="all=both modes (default), direct=one burst, staged=ramp ladder",
    )
    p.add_argument(
        "--n",
        type=int,
        default=int(os.getenv("BENCH_N", DEFAULT_N)),
        help=f"direct-mode concurrency (default {DEFAULT_N}, hard cap {HARD_N_CAP})",
    )
    p.add_argument(
        "--stages",
        type=str,
        default=os.getenv("BENCH_STAGES", ",".join(str(x) for x in DEFAULT_STAGES)),
        help="comma-separated staged sizes, e.g. 200,500,1000,2000",
    )
    p.add_argument(
        "--max-threads",
        type=int,
        default=int(os.getenv("BENCH_MAX_THREADS", DEFAULT_MAX_THREADS)),
        help=f"requests OS thread cap (default {DEFAULT_MAX_THREADS}, hard {HARD_THREAD_CAP})",
    )
    p.add_argument(
        "--max-connections",
        type=int,
        default=int(os.getenv("BENCH_MAX_CONNECTIONS", DEFAULT_MAX_CONNECTIONS)),
        help=f"async inflight socket cap (default {DEFAULT_MAX_CONNECTIONS}, hard {HARD_CONN_CAP})",
    )
    p.add_argument(
        "--libs",
        type=str,
        default=os.getenv("BENCH_LIBS", DEFAULT_LIBS),
        help="comma-separated: rusty-req,httpx,aiohttp,requests "
        "(high volume: omit requests)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="allow exceeding hard caps (DANGEROUS on macOS — can kernel panic)",
    )
    p.add_argument(
        "--single-timeout",
        type=float,
        default=float(os.getenv("BENCH_SINGLE_TIMEOUT", SINGLE_TIMEOUT)),
    )
    p.add_argument(
        "--total-timeout",
        type=float,
        default=float(os.getenv("BENCH_TOTAL_TIMEOUT", TOTAL_TIMEOUT)),
    )
    p.add_argument(
        "--delay",
        type=float,
        default=float(os.getenv("BENCH_DELAY", DELAY)),
    )
    return p.parse_args()


def _clamp_n(n: int, force: bool, label: str) -> int:
    if n <= 0:
        raise SystemExit(f"{label} must be > 0, got {n}")
    if force:
        return n
    if n > HARD_N_CAP:
        print(f"⚠️  {label}={n} exceeds hard cap {HARD_N_CAP}; clamping (use --force to override)")
        return HARD_N_CAP
    return n


async def main() -> int:
    global SINGLE_TIMEOUT, TOTAL_TIMEOUT, DELAY, results, MAX_THREADS, MAX_CONNECTIONS, ENABLED_LIBS
    args = parse_args()
    SINGLE_TIMEOUT = args.single_timeout
    TOTAL_TIMEOUT = args.total_timeout
    DELAY = args.delay
    results = []

    libs = [x.strip().lower() for x in args.libs.split(",") if x.strip()]
    # normalize aliases
    alias = {"rusty_req": "rusty-req", "rustyreq": "rusty-req"}
    libs = [alias.get(x, x) for x in libs]
    bad = [x for x in libs if x not in ALL_LIBS]
    if bad:
        raise SystemExit(f"unknown --libs {bad}; choose from {ALL_LIBS}")
    if not libs:
        raise SystemExit("--libs cannot be empty")
    ENABLED_LIBS = libs

    if args.force:
        MAX_THREADS = max(1, args.max_threads)
        MAX_CONNECTIONS = max(1, args.max_connections)
        print("⚠️  --force: hard caps disabled. High N/threads can kernel-panic macOS.")
    else:
        MAX_THREADS = max(1, min(args.max_threads, HARD_THREAD_CAP))
        MAX_CONNECTIONS = max(1, min(args.max_connections, HARD_CONN_CAP))
        if args.max_threads > HARD_THREAD_CAP:
            print(f"⚠️  --max-threads clamped to {HARD_THREAD_CAP}")
        if args.max_connections > HARD_CONN_CAP:
            print(f"⚠️  --max-connections clamped to {HARD_CONN_CAP}")

    n = _clamp_n(args.n, args.force, "N")
    stages = [int(x.strip()) for x in args.stages.split(",") if x.strip()]
    if not stages:
        stages = list(DEFAULT_STAGES)
    stages = [_clamp_n(s, args.force, f"stage") for s in stages]

    external = os.getenv("HTTPBIN_URL")
    server: Optional[_DelayServer] = None
    if external:
        base = external.rstrip("/")
        url = f"{base}/delay/{DELAY}"
        print(f"🌐 Using external service: {url}")
        try:
            r = requests.get(f"{base}/status/200", timeout=5)
            r.raise_for_status()
        except Exception as e:
            print(f"❌ external httpbin not reachable: {e}")
            return 1
    else:
        base, server = start_embedded_server()
        url = f"{base}/delay/{DELAY}"
        print(f"🌐 Embedded delay server: {url}")

    print("📦 Timeout Performance Comparison")
    print(f"  single_timeout={SINGLE_TIMEOUT}s  total_timeout={TOTAL_TIMEOUT}s  delay={DELAY}s")
    print(f"  mode={args.mode}  direct_n={n}  stages={stages}")
    print(f"  libs={list(ENABLED_LIBS)}")
    print(
        f"  safety: max_threads={MAX_THREADS}  max_connections={MAX_CONNECTIONS}  "
        f"hard_n={HARD_N_CAP}  (threads panic macOS; sockets stress Docker/kernel)"
    )
    print(f"  URL={url}")
    if "requests" in ENABLED_LIBS and (n >= 2000 or max(stages or [0]) >= 2000):
        print(
            "⚠️  High N + requests: threads are capped, so requests is NOT a fair "
            "1:1 concurrency peer. Prefer --libs rusty-req,aiohttp,httpx for volume."
        )

    try:
        import rusty_req  # noqa: F401
    except ImportError:
        print("❌ rusty_req not installed. Run: maturin develop --release")
        return 1

    try:
        if args.mode in ("all", "staged"):
            await run_staged(url, stages)
        if args.mode in ("all", "direct"):
            # if staged already covered max N, still run direct as separate labelled mode
            await run_direct(url, n)
    finally:
        if server is not None:
            server.shutdown()

    print("\n" + "=" * 80)
    print("Full results table:\n")
    print(markdown_table())
    print("\n" + "=" * 80)
    print("Pivot summary (success%/time):\n")
    print(summary_pivot())

    out = {
        "params": {
            "mode": args.mode,
            "n": n,
            "stages": stages,
            "delay": DELAY,
            "single_timeout": SINGLE_TIMEOUT,
            "total_timeout": TOTAL_TIMEOUT,
            "max_threads": MAX_THREADS,
            "max_connections": MAX_CONNECTIONS,
            "libs": list(ENABLED_LIBS),
            "url": url,
        },
        "results": results,
        "markdown": markdown_table(),
        "pivot": summary_pivot(),
    }
    out_path = os.path.join(os.path.dirname(__file__), "readme_timeout_comparison_result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Saved {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
