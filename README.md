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
    requests = [
        rusty_req.RequestItem(
            url="https://httpbin.org/headers",
            method="GET",
            params=None,
            timeout=3.0,
            tag=f"test-get-{i}",
            headers={
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "X-Test-Header": "ChatGPT"
            }
        )
        for i in range(100)
    ]

    start = time.perf_counter()
    
    rusty_req.set_debug(False)
    responses = await rusty_req.fetch_requests(requests, total_timeout=5.0)
    duration = time.perf_counter() - start

    success = sum(1 for r in responses if not r["error"])
    failure = len(responses) - success

    print(f"✅ 成功请求数: {success}")
    print(f"❌ 失败请求数: {failure}")
    print(f"⏱️ 总耗时: {duration:.2f} 秒")

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
[
    {
        "response": str | None,  # 成功时返回内容
        "error": str | None,     # 失败时错误信息
        "meta": {
            "tag": str,
            "elapsed_ms": float  # 请求耗时（毫秒）
        }
    },
    ...
]
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
