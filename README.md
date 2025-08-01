# rusty-req

A high-performance asynchronous request library based on Rust + Python, suitable for scenarios that require batch HTTP requests. It implements concurrent request logic in Rust and packages it into a Python module using [maturin](https://github.com/PyO3/maturin) , combining performance with ease of use.

## 🔧 Installation

```
pip install rusty-req
```

Or build from source:

```
maturin build --release
pip install target/wheels/rusty_req-*.whl
```

## Development & Debugging
```
cargo watch -s "maturin develop"
```

## 🚀 Features

- Batch asynchronous HTTP requests (supports GET / POST)
- Customizable headers / params / timeout / tag
- Global timeout control (total_timeout)
- Returns response body, exception info, and meta data
- Built with Rust + Tokio for high throughput

## 📦 Example Usage

```python
import asyncio
import time
import rusty_req


async def main():
    # Using JSONPlaceholder - a free test API
    requests = [
        rusty_req.RequestItem(
            url="https://httpbin.org/delay/2",
            method="GET",
            headers={
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "X-Test-Header": "ChatGPT"
            },
            timeout=2.9,
            tag=f"json-test-{i}",
        )
        for i in range(100)  # 100 concurrent requests
    ]

    # Disable debug logs
    rusty_req.set_debug(False)

    print("🚀 Starting 100 concurrent JSON API requests...")
    start_time = time.perf_counter()

    responses = await rusty_req.fetch_requests(
        requests,
        total_timeout=3.0
    )

    total_time = time.perf_counter() - start_time

    # Process results
    success = 0
    failed = 0
    status_codes = {}
    response_times = []

    for r in responses:
        if r.get("exception"):
            failed += 1
        else:
            meta = r.get("meta", {})
            status_code = meta.get("status_code", 0)
            process_time = float(meta.get("process_time", 0))

            status_codes[status_code] = status_codes.get(status_code, 0) + 1
            response_times.append(process_time)
            success += 1

    # Calculate metrics
    avg_response_time = sum(response_times) / len(response_times) if response_times else 0
    min_response_time = min(response_times) if response_times else 0
    max_response_time = max(response_times) if response_times else 0
    req_per_sec = success / total_time if total_time > 0 else 0

    print("\n📊 Load Test Summary:")
    print(f"⏱️ Total time: {total_time:.2f}s")
    print(f"📈 Requests per second: {req_per_sec:.1f}")
    print(f"✅ Successful requests: {success}")
    print(f"⚠️ Failed requests: {failed}")
    print(f"🔄 Status code distribution: {status_codes}")
    print(f"⏳ Response time - Avg: {avg_response_time:.4f}s, Min: {min_response_time:.4f}s, Max: {max_response_time:.4f}s")


if __name__ == "__main__":
    asyncio.run(main())

```

## 🧱 Data Structure

### `RequestItem` Parameters

| Field     | Type             | Required | Description                                         |
|------------|------------------|------|--------------------------------------------|
| `url`      | `str`            | ✅   | Target URL                                 |
| `method`   | `str`            | ✅   | HTTP method ("GET" or "POST")              |
| `params`   | `dict` / `None`  | No   | Query parameters (GET) or form data (POST) |
| `headers`  | `dict` / `None`  | No   | Custom HTTP headers                        |
| `timeout`  | `float`          | ✅   | Timeout for a single request (in seconds)  |
| `tag`      | `str`            | No   | Tag for tracing origin or indexing the request    |

### Response Format
```python
{
    "http_status": 200,
    "response": "{\"code\":403,\"msg\":\"Method Not Allowed.\"}",
    "meta": {
        "process_time": "0.2439",
        "request_time": "2025-07-29 19:17:11 -> 2025-07-29 19:17:11",
        "tag": "test-baidu1"
    },
    "exception": {
        "message": "HTTP status error: 500 - ", 
        "type": "HttpStatusError"
    }
}
```

## 📄 License

MIT License
