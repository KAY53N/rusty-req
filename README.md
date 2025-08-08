# rusty-req

A high-performance asynchronous request library based on Rust and Python, suitable for scenarios that require high-throughput concurrent HTTP requests. It implements the core concurrent logic in Rust and packages it into a Python module using [PyO3](https://pyo3.rs/) and [maturin](https://github.com/PyO3/maturin), combining Rust's performance with Python's ease of use.

## 🚀 Features

- **Dual Request Modes**: Supports both batch concurrent requests (`fetch_requests`) and single asynchronous requests (`fetch_single`).
- **High Performance**: Built with Rust, Tokio, and a shared `reqwest` client for maximum throughput.
- **Highly Customizable**: Allows custom headers, parameters/body, per-request timeouts, and tags.
- **Smart Response Handling**: Automatically decompresses `gzip`, `brotli`, and `deflate` encoded responses.
- **Global Timeout Control**: Use `total_timeout` in batch requests to prevent hangs.
- **Detailed Results**: Each response includes the HTTP status, body, metadata (like processing time), and any exceptions.
- **Debug Mode**: An optional debug mode (`set_debug(True)`) prints detailed request/response information.

## 🔧 Installation

```bash
pip install rusty-req
```

Or build from source:
```
# This will compile the Rust code and create a .whl file
maturin build --release

# Install from the generated wheel
pip install target/wheels/rusty_req-*.whl
```

## Development & Debugging
```
cargo watch -s "maturin develop"
```

## 📦 Example Usage
### 1. Fetching a Single Request (`fetch_single`)
Perfect for making a single asynchronous call and awaiting its result.

```python
import asyncio
import pprint
import rusty_req

async def single_request_example():
    """Demonstrates how to use fetch_single for a POST request."""
    print("🚀 Fetching a single POST request to httpbin.org...")

    # Enable debug mode to see detailed logs in the console
    rusty_req.set_debug(True)

    response = await rusty_req.fetch_single(
        url="https://httpbin.org/post",
        method="POST",
        params={"user_id": 123, "source": "example"},
        headers={"X-Client-Version": "1.0"},
        tag="my-single-post"
    )

    print("\n✅ Request finished. Response:")
    pprint.pprint(response)

if __name__ == "__main__":
    asyncio.run(single_request_example())```
```

### 2. Fetching Batch Requests (`fetch_requests`)

The core feature for handling a large number of requests concurrently. This example simulates a simple load test.
```python
import asyncio
import time
import rusty_req

async def batch_requests_example():
    """Demonstrates 100 concurrent requests with a global timeout."""
    requests = [
        rusty_req.RequestItem(
            url="https://httpbin.org/delay/2",  # This endpoint waits 2 seconds
            method="GET",
            timeout=2.9,  # Per-request timeout, should succeed
            tag=f"test-req-{i}",
        )
        for i in range(100)
    ]

    # Disable debug logs for cleaner output
    rusty_req.set_debug(False)

    print("🚀 Starting 100 concurrent requests...")
    start_time = time.perf_counter()

    # Set a global timeout of 3.0 seconds. Some requests will be cut off.
    responses = await rusty_req.fetch_requests(
        requests,
        total_timeout=3.0
    )

    total_time = time.perf_counter() - start_time

    # --- Process results ---
    success_count = 0
    failed_count = 0
    for r in responses:
        # Check the 'exception' field to see if the request was successful
        if r.get("exception") and r["exception"].get("type"):
            failed_count += 1
        else:
            success_count += 1

    print("\n📊 Load Test Summary:")
    print(f"⏱️  Total time taken: {total_time:.2f}s")
    print(f"✅ Successful requests: {success_count}")
    print(f"⚠️ Failed or timed-out requests: {failed_count}")

if __name__ == "__main__":
    asyncio.run(batch_requests_example())
```

## 🧱 Data Structure

### `RequestItem` Parameters

| Field     | Type             | Required | Description                                         |
|------------|------------------|------|--------------------------------------------|
| `url`      | `str`            | ✅   | Target URL                                 |
| `method`   | `str`            | ✅   | HTTP method        |
| `params`   | `dict` / `None`  | No   | For GET/DELETE, converted to URL query parameters. For POST/PUT/PATCH, sent as a JSON body. |
| `headers`  | `dict` / `None`  | No   | Custom HTTP headers                        |
| `timeout`  | `float`          | ✅   | Timeout for this single request in seconds. Defaults to 30s.  |
| `tag`      | `str`            | No   | An arbitrary tag to help identify or index the response.    |

### Response Dictionary Format
Both `fetch_single` and `fetch_requests` return a dictionary (or a list of dictionaries) with a consistent structure.

#### Example of a successful response:
```json
{
    "http_status": 200,
    "response": "{\"data\": \"...\", \"headers\": {\"...\"}}",
    "meta": {
        "process_time": "0.4531",
        "request_time": "2025-08-08 03:15:01 -> 2025-08-08 03:15:01",
        "tag": "my-single-post"
    },
    "exception": {}
}
```

#### Example of a failed response (e.g., timeout):
```json
{
    "http_status": 0,
    "response": "",
    "meta": {
        "process_time": "3.0012",
        "request_time": "2025-08-08 03:15:05 -> 2025-08-08 03:15:08",
        "tag": "test-req-50"
    },
    "exception": {
        "type": "Timeout",
        "message": "Request timeout after 3.00 seconds"
    }
}
```

## 📄 License
This project is licensed under the [MIT License](https://opensource.org/license/MIT).
