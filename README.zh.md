# rusty-req

[![PyPI version](https://img.shields.io/pypi/v/rusty-req)](https://pypi.org/project/rusty-req/)
[![PyPI downloads](https://img.shields.io/pypi/dm/rusty-req)](https://pypi.org/project/rusty-req/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python versions](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/downloads/)
[![GitHub issues](https://img.shields.io/github/issues/KAY53N/rusty-req)](https://github.com/KAY53N/rusty-req/issues)
[![Build Status](https://github.com/KAY53N/rusty-req/actions/workflows/build.yml/badge.svg)](https://github.com/KAY53N/rusty-req/actions/workflows/build.yml)
[![Cross Platform Test](https://github.com/KAY53N/rusty-req/actions/workflows/cross-platform-test.yml/badge.svg)](https://github.com/KAY53N/rusty-req/actions/workflows/cross-platform-test.yml)

基于 Rust 和 Python 的高性能异步请求库...

一个基于 Rust 和 Python 的高性能异步请求库，适用于需要高吞吐量并发 HTTP 请求的场景。核心并发逻辑使用 Rust 实现，并通过 [PyO3](https://pyo3.rs/) 和 [maturin](https://github.com/PyO3/maturin) 封装为 Python 模块，将 Rust 的性能优势与 Python 的易用性结合。

### 🌐 [English](README.md) | [中文](README.zh.md)

## 🚀 功能特性

- **双模式请求**：支持批量并发请求（`fetch_requests`）和单个异步请求（`fetch_single`）。
- **高性能**：使用 Rust、Tokio，并共享 `reqwest` 客户端以最大化吞吐量。
- **高度可定制**：支持自定义请求头、参数/请求体、每个请求的超时及标签。
- **灵活的并发模式**：可选择 `SELECT_ALL`（默认，按完成顺序返回结果）或 `JOIN_ALL`（等待所有请求完成再返回）。
- **智能响应处理**：自动解压 `gzip`、`brotli` 和 `deflate` 编码的响应。
- **全局超时控制**：批量请求可设置 `total_timeout` 防止挂起。
- **详细结果**：每个响应包含 HTTP 状态、响应体、元信息（如处理时间）及异常信息。
- **调试模式**：可选调试模式 (`set_debug(True)`) 打印详细请求/响应日志。

## 🔧 安装

```bash
pip install rusty-req
```
或从源码构建：
```
# 编译 Rust 代码并生成 .whl 文件
maturin build --release

# 安装生成的 wheel
pip install target/wheels/rusty_req-*.whl
```

## 开发与调试
```
cargo watch -s "maturin develop"
```

## ⚙️ 代理配置 & 调试

### 1. 使用代理

如果需要通过代理访问外部网络，可以创建 `ProxyConfig` 对象并设置为全局代理：

```python
import asyncio
import rusty_req

async def proxy_example():
  # 创建 ProxyConfig 对象
  proxy = rusty_req.ProxyConfig(
    http="http://127.0.0.1:7890",
    https="http://127.0.0.1:7890"
  )

  # 设置全局代理（所有请求都会使用该代理）
  await rusty_req.set_global_proxy(proxy)

  # 发起请求（将自动通过代理）
  resp = await rusty_req.fetch_single(url="https://httpbin.org/get")
  print(resp)

if __name__ == "__main__":
  asyncio.run(proxy_example())
```

### 2. 调试日志

`set_debug` 用于启用调试模式，支持 **控制台输出** 和 **日志文件记录**：

```python
import rusty_req

# 仅在控制台打印调试信息
rusty_req.set_debug(True)

# 同时打印到控制台并写入日志文件
rusty_req.set_debug(True, "logs/debug.log")

# 关闭调试模式
rusty_req.set_debug(False)
```

## 📦 使用示例
### 1. 单个请求 (`fetch_single`)
适合单个异步请求并等待结果的场景。

```python
import asyncio
import pprint
import rusty_req

async def single_request_example():
    """示例：使用 fetch_single 发起 POST 请求"""
    print("🚀 正在向 httpbin.org 发送单个 POST 请求...")

    rusty_req.set_debug(True)  # 开启调试模式

    response = await rusty_req.fetch_single(
        url="https://httpbin.org/post",
        method="POST",
        params={"user_id": 123, "source": "example"},
        headers={"X-Client-Version": "1.0"},
        tag="my-single-post"
    )

    print("\n✅ 请求完成，响应如下：")
    pprint.pprint(response)

if __name__ == "__main__":
    asyncio.run(single_request_example())

```

### 2. 批量请求 (`fetch_requests`)

适合高并发场景或压力测试。
```python
import asyncio
import time
import rusty_req
from rusty_req import ConcurrencyMode

async def batch_requests_example():
    """示例：100 个并发请求，设置全局超时"""
    requests = [
        rusty_req.RequestItem(
            url="https://httpbin.org/delay/2",
            method="GET",
            timeout=2.9,  # 每个请求的超时
            tag=f"test-req-{i}",
        )
        for i in range(100)
    ]

    rusty_req.set_debug(False)  # 关闭调试日志

    print("🚀 开始 100 个并发请求...")
    start_time = time.perf_counter()

    responses = await rusty_req.fetch_requests(
        requests,
        total_timeout=3.0,  # 批量请求全局超时
        mode=ConcurrencyMode.SELECT_ALL
    )

    total_time = time.perf_counter() - start_time

    success_count = 0
    failed_count = 0
    for r in responses:
        if r.get("exception") and r["exception"].get("type"):
            failed_count += 1
        else:
            success_count += 1

    print("\n📊 压力测试结果：")
    print(f"⏱️  总耗时: {total_time:.2f}s")
    print(f"✅ 成功请求数: {success_count}")
    print(f"⚠️ 超时或失败请求数: {failed_count}")

if __name__ == "__main__":
    asyncio.run(batch_requests_example())

```

### 3. 并发模式对比 (`SELECT_ALL` vs `JOIN_ALL`)

`fetch_requests` 函数支持两种强大的并发策略，选择合适的策略对于构建健壮的应用非常关键。

- **`ConcurrencyMode.SELECT_ALL`（默认）：尽力收集模式**  
  该模式按照“先完成先返回”或“尽力而为”的原则工作，目标是在指定的 `total_timeout` 时间内尽可能多地收集成功结果。
    - 请求一完成就立即返回结果。
    - 如果达到 `total_timeout`，会优雅地返回已经完成的请求结果，同时将仍在等待的请求标记为超时。
    - **单个请求失败不会影响其他请求。**

- **`ConcurrencyMode.JOIN_ALL`：事务性模式（全有或全无）**  
  该模式将整个批次视为一个原子事务，要求更严格。
    - 会等待 **所有** 提交的请求完成后再处理结果。
    - 然后对结果进行检查。
    - **成功情况**：仅当 *每一个请求都成功* 时，才会返回完整的成功结果列表。
    - **失败情况**：如果 *任意一个请求失败*（例如单个超时、网络错误或非 2xx 状态码），整个批次将被视为失败，并返回一个列表，其中 **每个请求都被标记为全局失败**。

### 4. 超时性能对比

在相同测试条件下（全局超时 3 秒，每个请求超时 2.6 秒，httpbin 延迟 2.3 秒），我们对比了不同库的性能：

| 库 / 框架           | 请求总数 | 成功数 | 超时数 | 成功率 | 实际总耗时  | 说明 / 特点 |
|--------------------|---------|--------|--------|--------|--------|------------|
| **Rusty-req**      | 1000    | 1000   | 0      | 100.0% | 2.56s  | 高并发下性能稳定；可以精确控制每个请求和全局超时 |
| **httpx**          | 1000    | 0      | 0      | 0.0%   | 26.77s | 超时参数未生效，整体性能异常 |
| **aiohttp**        | 1000    | 100    | 900    | 10.0%  | 2.66s  | 单请求超时有效，但全局超时控制不足 |
| **requests**       | 1000    | 1000   | 0      | 100.0% | 3.45s  | 同步阻塞模式，不适合大规模并发请求 |

关键结论：
- **Rusty-req** 可以在严格的全局超时限制下完成任务，同时保持高并发和稳定性。
- 传统异步库在全局超时和极高并发场景下表现欠佳。
- 同步库如 `requests` 虽然能得到正确结果，但不适合大规模并发请求。

![超时性能对比](https://raw.githubusercontent.com/KAY53N/rusty-req/main/docs/images/timeout_performance_comparison.png)

---

### 快速对比

| 方面                    | `ConcurrencyMode.SELECT_ALL`（默认）                               | `ConcurrencyMode.JOIN_ALL`                                          |
| :---------------------- | :---------------------------------------------------------------- | :----------------------------------------------------------------- |
| **失败处理**            | **宽容**。单个请求失败不会影响其他成功请求。                       | **严格 / 原子**。单个请求失败会导致整个批次失败。                 |
| **主要使用场景**        | 最大化吞吐量；尽可能获取更多数据。                                 | 任务必须全部成功或全部失败（例如事务操作）。                        |
| **结果顺序**            | 按完成时间返回（最快的先返回）。                                   | 按原提交顺序返回。                                                 |
| **何时获取结果**        | 请求完成即返回，逐个获取。                                         | 所有请求完成并验证后一次性返回。                                     |

---

### 代码示例

下面的示例清楚地演示了两种模式的行为差异。

```python
import asyncio
import rusty_req
from rusty_req import ConcurrencyMode

async def concurrency_modes_example():
    """演示 SELECT_ALL 和 JOIN_ALL 模式的区别。"""
    # 注意：这里使用一个返回 500 的接口以触发失败。
    requests = [
        rusty_req.RequestItem(url="https://httpbin.org/delay/2", tag="should_succeed"),
        rusty_req.RequestItem(url="https://httpbin.org/status/500", tag="will_fail"),
        rusty_req.RequestItem(url="https://httpbin.org/delay/1", tag="should_also_succeed"),
    ]

    # --- 1. 测试 SELECT_ALL ---
    print("--- 🚀 测试 SELECT_ALL（尽力收集模式） ---")
    results_select = await rusty_req.fetch_requests(
        requests,
        mode=ConcurrencyMode.SELECT_ALL,
        total_timeout=3.0
    )

    print("结果:")
    for res in results_select:
        tag = res.get("meta", {}).get("tag")
        status = res.get("http_status")
        err_type = res.get("exception", {}).get("type")
        print(f"  - Tag: {tag}, Status: {status}, Exception: {err_type}")

    print("\n" + "="*50 + "\n")

    # --- 2. 测试 JOIN_ALL ---
    print("--- 🚀 测试 JOIN_ALL（全有或全无模式） ---")
    results_join = await rusty_req.fetch_requests(
        requests,
        mode=ConcurrencyMode.JOIN_ALL,
        total_timeout=3.0
    )

    print("结果:")
    for res in results_join:
        tag = res.get("meta", {}).get("tag")
        status = res.get("http_status")
        err_type = res.get("exception", {}).get("type")
        print(f"  - Tag: {tag}, Status: {status}, Exception: {err_type}")

if __name__ == "__main__":
    asyncio.run(concurrency_modes_example())
```
上述脚本的预期输出：

```
--- 🚀 测试 SELECT_ALL（尽力收集模式） ---
结果:
- Tag: should_also_succeed, Status: 200, Exception: None
- Tag: will_fail, Status: 500, Exception: HttpStatusError
- Tag: should_succeed, Status: 200, Exception: None

==================================================

--- 🚀 测试 JOIN_ALL（全有或全无模式） ---
结果:
- Tag: should_succeed, Status: 0, Exception: GlobalTimeout
- Tag: will_fail, Status: 0, Exception: GlobalTimeout
- Tag: should_also_succeed, Status: 0, Exception: GlobalTimeout
```

## 🧱 数据结构

### `RequestItem` 参数

| 字段             | 类型              | 必填 | 描述                                                                    |
|:---------------|:----------------| :--: |:----------------------------------------------------------------------|
| `url`          | `str`           | ✅   | 目标 URL 地址。                                                            |
| `method`       | `str`           | ✅   | HTTP 请求方法。                                                            |
| `params`       | `dict` / `None` | 否   | 对于 GET/DELETE 请求，会转换为 URL 查询参数；对于 POST/PUT/PATCH 请求，会作为 JSON body 发送。 |
| `headers`      | `dict` / `None` | 否   | 自定义 HTTP 请求头。                                                         |
| `tag`          | `str`           | 否   | 用于标记请求或索引响应的任意字符串标签。                                                  |
| `http_version` | `str`           | 否   | 指定的http版本，默认行为是“Auto”，优先尝试 HTTP/2，如果不支持则回退 HTTP/1.1          |
| `ssl_verify`   | `bool`          | 否   | **SSL 证书验证** (默认 `True` 启用验证，设为 `False` 可禁用以支持自签名证书) |
| `timeout`      | `float`         | ✅   | 单个请求的超时时间（秒），默认 30 秒。                                                 |

---

### `ProxyConfig` 参数

| 字段         | 类型                  | 必填    | 描述                                                                 |
|:------------|:---------------------|:--------|:--------------------------------------------------------------------|
| `http`      | `str` / `None`       | 否      | HTTP 请求使用的代理地址（例如：`http://127.0.0.1:8080`）。           |
| `https`     | `str` / `None`       | 否      | HTTPS 请求使用的代理地址。                                          |
| `all`       | `str` / `None`       | 否      | 同时应用于所有协议的代理地址，会覆盖 `http` 和 `https`。            |
| `no_proxy`  | `List[str]` / `None` | 否      | 不使用代理的主机名或 IP 列表。                                      |
| `username`  | `str` / `None`       | 否      | 可选的代理认证用户名。                                              |
| `password`  | `str` / `None`       | 否      | 可选的代理认证密码。                                                |
| `trust_env` | `bool` / `None`      | 否      | 是否信任系统环境变量中的代理配置（如 `HTTP_PROXY`、`NO_PROXY`）。   |

---

### `fetch_requests` 参数

| 字段             | 类型                  | 必填 | 描述                                                                                     |
| :--------------- | :-------------------- | :--: | :--------------------------------------------------------------------------------------- |
| `requests`       | `List[RequestItem]`   | ✅   | 待并发执行的 `RequestItem` 列表。                                                       |
| `total_timeout`  | `float`               | 否   | 整个批量请求的全局超时时间（秒）。                                                      |
| `mode`           | `ConcurrencyMode`     | 否   | 并发策略。`SELECT_ALL`（默认）为尽力收集模式，`JOIN_ALL` 为原子执行模式（全有或全无）。详见第 3 节。 |

---

### `fetch_single` 参数

| 字段          | 类型                  | 必填    | 描述                                                                                                         |
|:--------------|:--------------------|:--------|:------------------------------------------------------------------------------------------------------------|
| `url`         | `str`               | ✅      | 目标请求的 URL。                                                                                             |
| `method`      | `str` / `None`      | 否      | HTTP 请求方法，例如 `"GET"`、`"POST"`，默认可由客户端自行处理。                                               |
| `params`      | `dict` / `None`     | 否      | 请求参数。对于 GET/DELETE 请求，会被转换为 URL 查询参数；对于 POST/PUT/PATCH 请求，会作为 JSON body 发送。   |
| `timeout`     | `float` / `None`    | 否      | 当前请求的超时时间（秒），默认值可为 30 秒。                                                               |
| `headers`     | `dict` / `None`     | 否      | 自定义 HTTP 请求头。                                                                                         |
| `tag`         | `str` / `None`      | 否      | 任意标签，用于标识或索引请求响应。                                                                         |
| `proxy`       | `ProxyConfig` / `None` | 否   | 可选代理配置，若提供则应用于此请求。                                                                       |
| `http_version`| `HttpVersion` / `None` | 否   | HTTP 版本选择，通常支持 `"Auto"`（尝试 HTTP/2，失败回退 HTTP/1.1）、`"1.1"`、`"2"` 等。                      |
| `ssl_verify`  | `bool` / `None`     | 否      | 是否验证 SSL 证书，默认 `True`，若为 `False` 则忽略自签名证书验证。                                         |

---

### 响应字典格式

`fetch_single` 和 `fetch_requests` 返回的结果都为字典（或字典列表），结构统一。

#### 成功响应示例：

```json
{
  "http_status": 200,
  "response": {
    "headers": {
      "access-control-allow-credentials": "true",
      "access-control-allow-origin": "*",
      "connection": "keep-alive",
      "content-length": "314",
      "content-type": "application/json",
      "date": "Wed, 10 Sep 2025 03:15:31 GMT",
      "server": "gunicorn/19.9.0"
    },
    "content": "{\"data\":\"...\", \"headers\":{\"...\"}}"
  },
  "meta": {
    "process_time": "2.0846",
    "request_time": "2025-09-10 11:22:46 -> 2025-09-10 11:22:48",
    "tag": "req-0"
  },
  "exception": {}
}
```

#### 失败响应示例（例如超时）：
```json
{
  "http_status": 0,
  "response": {
    "headers": {
      "access-control-allow-credentials": "true",
      "access-control-allow-origin": "*",
      "connection": "keep-alive",
      "content-length": "314",
      "content-type": "application/json",
      "date": "Wed, 10 Sep 2025 03:15:31 GMT",
      "server": "gunicorn/19.9.0"
    },
    "content": ""
  },
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

---

## 更新日志

查看详细更新内容请访问 [CHANGELOG](CHANGELOG.md)

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=KAY53N/rusty-req&type=Date)](https://www.star-history.com/#KAY53N/rusty-req&Date)


## 📄 许可证
本项目采用 [MIT License](https://opensource.org/license/MIT).
