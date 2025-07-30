# rusty-req


基于 Rust + Python 的高性能异步请求库，适用于需要批量发送 HTTP 请求的场景。通过 Rust 实现并发请求逻辑，并通过 [maturin](https://github.com/PyO3/maturin) 封装为 Python 模块，兼具性能与易用性。

## 🔧 安装

```bash
pip install rusty-req
```

或从源码构建：

```bash
maturin build --release
pip install target/wheels/rusty_req-*.whl
```

## 开发调试
```
cargo watch -s "maturin develop"
```

## 🚀 功能特点

- 批量异步发送 HTTP 请求（支持 GET / POST）
- 支持自定义 headers / params / timeout / tag
- 支持全局超时时间控制（`total_timeout`）
- 返回响应内容、错误信息、Meta 数据
- 使用 Rust + Tokio 提升吞吐能力

## 📦 使用示例

```python
import asyncio
import time
import rusty_req


async def main():
    # Using JSONPlaceholder - a free fake API for testing
    requests = [
        rusty_req.RequestItem(
            url="https://httpbin.org/delay/2",
            method="GET",
            timeout=2.9,
            tag=f"json-test-{i}",
        )
        for i in range(100)  # 100 concurrent requests
    ]

    # Disable debug output
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
            meta = r.get('meta', {})
            status_code = meta.get("status_code", 0)
            process_time = meta.get("process_time", 0)

            status_codes[status_code] = status_codes.get(status_code, 0) + 1
            response_times.append(process_time)
            success += 1

    # Calculate statistics
    avg_response_time = sum(response_times) / len(response_times) if response_times else 0
    min_response_time = min(response_times) if response_times else 0
    max_response_time = max(response_times) if response_times else 0
    req_per_sec = success / total_time if total_time > 0 else 0

    print("\n📊 Load Test Results:")
    print(f"⏱️ Total time: {total_time:.2f}s")
    print(f"📈 Requests/sec: {req_per_sec:.1f}")
    print(f"✅ Successful: {success}")
    print(f"⚠️ Failed: {failed}")
    print(f"🔄 Status codes: {status_codes}")
    print(
        f"⏳ Response times - Avg: {avg_response_time:.4f}s, Min: {min_response_time:.4f}s, Max: {max_response_time:.4f}s")


if __name__ == "__main__":
    asyncio.run(main())
```

## 🧱 数据结构说明

### `RequestItem` 参数

| 字段名     | 类型             | 必须 | 说明                                   |
|------------|------------------|------|----------------------------------------|
| `url`      | `str`            | ✅   | 请求地址                               |
| `method`   | `str`            | ✅   | 请求方法（`"GET"` 或 `"POST"`）        |
| `params`   | `dict` / `None`  | 否   | 查询参数（GET）或表单数据（POST）      |
| `headers`  | `dict` / `None`  | 否   | 自定义请求头                           |
| `timeout`  | `float`          | ✅   | 单个请求超时（秒）                     |
| `tag`      | `str`            | 否   | 标记请求的来源、编号等辅助信息         |

### 返回格式

```python
{
    "response": "{\"code\":403,\"msg\":\"Method Not Allowed.\"}",
    "meta": {
        "process_time": "0.2439",
        "request_time": "2025-07-29 19:17:11 -> 2025-07-29 19:17:11",
        "tag": "test-baidu1"
    }，
    "exception": {
        "message": "HTTP status error: 500 - ", 
        "type": "HttpStatusError"
    }
}
```

## 📑 Headers 示例

```python
RequestItem(
    url="https://httpbin.org/headers",
    method="GET",
    headers={
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "X-Test-Header": "ChatGPT"
    },
    timeout=5.0
)
```

## 📄 License

MIT License
