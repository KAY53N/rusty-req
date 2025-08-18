#![allow(non_local_definitions)]
// PyO3 宏和类型
use pyo3::{pyclass, pymethods, pyfunction, pymodule};
use pyo3::{PyResult, Python, PyAny, Py, wrap_pyfunction};
use pyo3::types::{PyDict, PyList, PyModule};
use pyo3::IntoPy;

// 其他库
use std::collections::HashMap;
use reqwest::{Client, Request, StatusCode};
use std::time::{Duration, SystemTime};
use futures::future::{join_all};
use serde_json::Value;
use chrono::{DateTime, Local};
use once_cell::sync::Lazy;
use tokio::sync::Mutex;
use std::sync::atomic::{AtomicBool, Ordering};
use reqwest::header::{HeaderMap, HeaderName, HeaderValue, ACCEPT_ENCODING};
use std::pin::Pin;
use futures::stream::{FuturesUnordered};
use futures::StreamExt;   // 这个必须单独引入

static DEBUG_MODE: AtomicBool = AtomicBool::new(false);

// 全局共享的HTTP客户端
static GLOBAL_CLIENT: Lazy<Mutex<Client>> = Lazy::new(|| {
    Mutex::new(Client::builder()
        .timeout(Duration::from_secs(30))
        .gzip(true)       // 开启 gzip 自动解压
        .brotli(true)     // 开启 brotli 自动解压
        .deflate(true)    // 开启 deflate 自动解压
        .build()
        .expect("Failed to create HTTP client"))
});

// 新增：并发策略枚举
#[pyclass]
#[derive(Clone, PartialEq)]
pub enum ConcurrencyMode {
    #[pyo3(name = "SELECT_ALL")]
    SelectAll,
    #[pyo3(name = "JOIN_ALL")]
    JoinAll,
}

#[pymethods]
impl ConcurrencyMode {
    #[new]
    fn new() -> Self {
        ConcurrencyMode::SelectAll
    }

    #[classattr]
    const SELECT_ALL: ConcurrencyMode = ConcurrencyMode::SelectAll;

    #[classattr]
    const JOIN_ALL: ConcurrencyMode = ConcurrencyMode::JoinAll;

    fn __str__(&self) -> String {
        match self {
            ConcurrencyMode::SelectAll => "SELECT_ALL".to_string(),
            ConcurrencyMode::JoinAll => "JOIN_ALL".to_string(),
        }
    }

    fn __repr__(&self) -> String {
        format!("ConcurrencyMode.{}", self.__str__())
    }
}

#[pyfunction]
fn set_debug(enabled: bool) {
    DEBUG_MODE.store(enabled, Ordering::Relaxed);
}

pub fn is_debug() -> bool {
    DEBUG_MODE.load(Ordering::Relaxed)
}

fn debug_log(
    tag: &str,
    request: &Request,
    status: StatusCode,
    headers: &HeaderMap,
    body: &str,
) {
    if !is_debug() {
        return;
    }

    println!("\n================== [DEBUG: {}] ==================", tag);
    println!("Request Method : {}", request.method());
    println!("Request URL    : {}", request.url());
    println!("--------------------------------------------------");
    println!("Response Status: {}", status);
    println!("Response Headers:");
    for (key, value) in headers.iter() {
        println!("  {}: {:?}", key, value);
    }
    println!("--------------------------------------------------");
    println!("Response Body:\n{}", body);
    println!("==================================================\n");
}

#[pyclass]
#[derive(Clone)]
pub struct RequestItem {
    #[pyo3(get, set)]
    pub url: String,
    #[pyo3(get, set)]
    pub method: Option<String>,
    #[pyo3(get, set)]
    pub params: Option<Py<PyDict>>,
    #[pyo3(get, set)]
    pub timeout: Option<f64>,
    #[pyo3(get, set)]
    pub tag: Option<String>,
    #[pyo3(get, set)]
    pub headers: Option<Py<PyDict>>,
}

#[pymethods]
impl RequestItem {
    #[new]
    fn new(
        url: String,
        method: Option<String>,
        params: Option<Py<PyDict>>,
        timeout: Option<f64>,
        tag: Option<String>,
        headers: Option<Py<PyDict>>,
    ) -> Self {
        Self { url, method, params, timeout, tag, headers }
    }
}

fn py_to_json(py: Python, obj: &PyAny) -> PyResult<Value> {
    if let Ok(b) = obj.extract::<bool>() {
        return Ok(Value::Bool(b));
    }
    if let Ok(s) = obj.extract::<String>() {
        Ok(Value::String(s))
    } else if let Ok(i) = obj.extract::<i64>() {
        Ok(Value::Number(i.into()))
    } else if let Ok(f) = obj.extract::<f64>() {
        Ok(Value::Number(serde_json::Number::from_f64(f).unwrap_or(0.into())))
    } else if let Ok(list) = obj.downcast::<PyList>() {
        let mut vec = Vec::new();
        for item in list.iter() {
            vec.push(py_to_json(py, item)?);
        }
        Ok(Value::Array(vec))
    } else if let Ok(dict) = obj.downcast::<PyDict>() {
        let mut map = serde_json::Map::new();
        for (key, value) in dict.iter() {
            let key_str = key.to_string();
            map.insert(key_str, py_to_json(py, value)?);
        }
        Ok(Value::Object(map))
    } else {
        Ok(Value::String(obj.to_string()))
    }
}

// 创建全局超时的结果
fn create_global_timeout_result(req: &RequestItem) -> HashMap<String, String> {
    let mut result = HashMap::new();
    result.insert("http_status".to_string(), "0".to_string());
    result.insert("response".to_string(), String::new());

    let mut exc = serde_json::Map::new();
    exc.insert("type".to_string(), Value::String("GlobalTimeout".to_string()));
    exc.insert("message".to_string(), Value::String("Request timed out due to global timeout".to_string()));
    result.insert("exception".to_string(), Value::Object(exc).to_string());

    let mut meta = serde_json::Map::new();
    meta.insert("request_time".to_string(), Value::String("".to_string()));
    meta.insert("process_time".to_string(), Value::String("0.0000".to_string()));
    if let Some(tag) = req.tag.clone() {
        meta.insert("tag".to_string(), Value::String(tag));
    }
    result.insert("meta".to_string(), Value::Object(meta).to_string());
    result
}

// 提取单个请求执行逻辑
async fn execute_single_request(
    req: RequestItem,
    client: Client
) -> HashMap<String, String> {
    let mut result = HashMap::new();
    result.insert("response".to_string(), String::new());

    let start = SystemTime::now();

    // 构建请求
    let builder = Python::with_gil(|py| -> reqwest::RequestBuilder {
        let method_str = req.method
            .as_deref()
            .unwrap_or("GET")
            .to_uppercase();

        let method = method_str.parse::<reqwest::Method>().unwrap_or_else(|_| reqwest::Method::GET);

        let mut builder = client.request(method.clone(), &req.url);

        // 设置 Header
        let mut headers = HeaderMap::new();

        // 默认值
        headers.insert(ACCEPT_ENCODING, HeaderValue::from_static("gzip, deflate, br"));

        // 如果 Python 中传了 headers，就覆盖或追加
        if let Some(py_headers) = &req.headers {
            if let Ok(dict) = py_headers.as_ref(py).downcast::<PyDict>() {
                for (k, v) in dict.iter() {
                    if let (Ok(k_str), Ok(v_str)) = (k.extract::<String>(), v.extract::<String>()) {
                        if let (Ok(h_name), Ok(h_val)) = (
                            HeaderName::from_bytes(k_str.as_bytes()),
                            HeaderValue::from_str(&v_str),
                        ) {
                            headers.insert(h_name, h_val);
                        }
                    }
                }
            }
        }

        builder = builder.headers(headers);

        // 设置参数：GET 用 query，POST/PUT/PATCH 用 JSON body
        if let Some(params_dict) = &req.params {
            if let Ok(dict) = params_dict.as_ref(py).downcast::<PyDict>() {
                if let Ok(json_value) = py_to_json(py, dict) {
                    match method {
                        reqwest::Method::GET | reqwest::Method::DELETE => {
                            if let Some(obj) = json_value.as_object() {
                                let mut query_params = Vec::new();
                                for (k, v) in obj {
                                    query_params.push((k.as_str(), v.to_string()));
                                }
                                builder = builder.query(&query_params);
                            }
                        }
                        _ => {
                            builder = builder.json(&json_value);
                        }
                    }
                }
            }
        }

        builder
    });

    // 发起请求，使用单个请求超时控制
    let timeout = Duration::from_secs_f64(req.timeout.unwrap_or(30.0).max(3.0));
    let tag = req.tag.clone().unwrap_or_else(|| "no-tag".to_string());
    let request_to_send = builder.try_clone().unwrap().build().unwrap();

    match tokio::time::timeout(timeout, builder.send()).await {
        Ok(Ok(res)) => {
            let status = res.status();
            result.insert("http_status".to_string(), status.as_u16().to_string());

            let headers = res.headers().clone();
            let text = res.text().await.unwrap_or_else(|e| format!("Failed to read response text: {}", e));

            debug_log(&tag, &request_to_send, status, &headers, &text);

            if !status.is_success() {
                // 状态码非 2xx，构造异常
                let mut exc = serde_json::Map::new();
                exc.insert("type".to_string(), Value::String("HttpStatusError".to_string()));
                exc.insert("message".to_string(), Value::String(format!("HTTP status error: {}", status.as_u16())));
                result.insert("exception".to_string(), Value::Object(exc).to_string());
            } else {
                result.insert("exception".to_string(), "{}".to_string());
                result.insert("response".to_string(), text);
            }
        }
        Ok(Err(e)) => {
            result.insert("http_status".to_string(), "0".to_string());
            let mut exc = serde_json::Map::new();
            exc.insert("type".to_string(), Value::String("HttpError".to_string()));
            exc.insert("message".to_string(), Value::String(format!("Request error: {}", e)));
            result.insert("exception".to_string(), Value::Object(exc).to_string());
        }
        Err(_) => {
            result.insert("http_status".to_string(), "0".to_string());
            let err_msg = format!("Request timeout after {:.2} seconds", timeout.as_secs_f64());
            let mut exc = serde_json::Map::new();
            exc.insert("type".to_string(), Value::String("Timeout".to_string()));
            exc.insert("message".to_string(), Value::String(err_msg));
            result.insert("exception".to_string(), Value::Object(exc).to_string());
        }
    }

    // 记录 meta 信息
    let end = SystemTime::now();
    let process_time = end.duration_since(start)
        .unwrap_or(Duration::from_secs(0))
        .as_secs_f64();
    let start_str = format_datetime(start);
    let end_str = format_datetime(end);

    let mut meta = serde_json::Map::new();
    meta.insert("request_time".to_string(), Value::String(format!("{} -> {}", start_str, end_str)));
    meta.insert("process_time".to_string(), Value::String(format!("{:.4}", process_time)));
    if let Some(tag) = req.tag.clone() {
        meta.insert("tag".to_string(), Value::String(tag));
    }
    result.insert("meta".to_string(), Value::Object(meta).to_string());
    result
}

/// 执行一批请求，使用 `FuturesUnordered` 进行流式并发处理。
async fn execute_with_select_all(
    requests: Vec<RequestItem>,
    total_duration: Duration,
    client: Client,
) -> Vec<HashMap<String, String>> {
    let total_requests = requests.len();
    let mut results = vec![None; total_requests];

    // 创建所有任务
    let mut futures = FuturesUnordered::new();
    for (index, req) in requests.iter().enumerate() {
        let client = client.clone();
        let req = req.clone();
        futures.push(async move {
            let result = execute_single_request(req, client).await;
            (index, result)
        });
    }

    // 带总超时的流式处理
    let collection_task = async {
        while let Some((index, result)) = futures.next().await {
            results[index] = Some(result);
        }
    };

    // 应用总超时
    let _ = tokio::time::timeout(total_duration, collection_task).await;

    // 为未完成的请求填充全局超时结果
    for (i, result_slot) in results.iter_mut().enumerate() {
        if result_slot.is_none() {
            *result_slot = Some(create_global_timeout_result(&requests[i]));
        }
    }

    results.into_iter().map(|opt| opt.unwrap()).collect()
}

// JOIN_ALL 模式实现 - 修改版本（原子性操作）
async fn execute_with_join_all(
    requests: Vec<RequestItem>,
    total_duration: Duration,
    client: Client,
) -> Vec<HashMap<String, String>> {
    // 创建所有 futures
    let request_futures: Vec<Pin<Box<dyn std::future::Future<Output = HashMap<String, String>> + Send>>> =
        requests.iter().map(|req| {
            let client = client.clone();
            let req = req.clone();
            Box::pin(async move {
                execute_single_request(req, client).await
            }) as Pin<Box<dyn std::future::Future<Output = HashMap<String, String>> + Send>>
        }).collect();

    // 使用 join_all 等待所有请求完成，带总超时控制
    match tokio::time::timeout(total_duration, join_all(request_futures)).await {
        Ok(completed_results) => {
            // 检查是否所有请求都成功（即没有异常）
            let all_success = completed_results.iter().all(|result| {
                if let Some(exc_str) = result.get("exception") {
                    exc_str == "{}" // 空的异常对象表示成功
                } else {
                    false
                }
            });

            if all_success {
                // 所有请求都成功，返回实际结果
                completed_results
            } else {
                // 有请求失败，全部标记为全局超时
                requests.iter().map(|req| create_global_timeout_result(req)).collect()
            }
        }
        Err(_) => {
            // 总超时，为所有请求创建全局超时结果
            requests.iter().map(|req| create_global_timeout_result(req)).collect()
        }
    }
}

// 转换结果为Python对象
fn convert_results_to_python(results: Vec<HashMap<String, String>>) -> PyResult<Vec<Py<PyAny>>> {
    Python::with_gil(|py| {
        results.into_iter().map(|res| {
            let dict = PyDict::new(py);

            dict.set_item("response", &res["response"])?;

            if let Some(http_status_str) = res.get("http_status") {
                if let Ok(http_status_int) = http_status_str.parse::<u16>() {
                    dict.set_item("http_status", http_status_int)?;
                } else {
                    dict.set_item("http_status", http_status_str)?;
                }
            }

            let meta_json_str = res.get("meta").map(|s| s.as_str()).unwrap_or("{}");
            let meta_pyobj = py.import("json")?.call_method1("loads", (meta_json_str,))?;
            dict.set_item("meta", meta_pyobj)?;

            if let Some(exc_str) = res.get("exception") {
                let exc_obj = py.import("json")?.call_method1("loads", (exc_str,))?;
                dict.set_item("exception", exc_obj)?;
            }

            Ok(dict.into_py(py))
        }).collect::<PyResult<Vec<Py<PyAny>>>>()
    })
}

#[pyfunction]
fn fetch_single<'py>(
    py: Python<'py>,
    url: String,
    method: Option<String>,
    params: Option<Py<PyDict>>,
    timeout: Option<f64>,
    headers: Option<Py<PyDict>>,
    tag: Option<String>,
) -> PyResult<&'py PyAny> {
    pyo3_asyncio::tokio::future_into_py(py, async move {
        let client = GLOBAL_CLIENT.lock().await.clone();
        let mut result = HashMap::new();
        result.insert("response".to_string(), String::new());

        let start = SystemTime::now();

        // 构建请求
        let builder = Python::with_gil(|py| -> reqwest::RequestBuilder {
            let method_str = method
                .as_deref()
                .unwrap_or("GET")
                .to_uppercase();

            let method = match method_str.parse::<reqwest::Method>() {
                Ok(m) => m,
                Err(_) => reqwest::Method::GET,
            };

            let mut builder = client.request(method.clone(), &url);

            // 设置 Header
            let mut headers_map = HeaderMap::new();

            // 如果传了 headers，就覆盖或追加
            if let Some(py_headers) = &headers {
                if let Ok(dict) = py_headers.as_ref(py).downcast::<PyDict>() {
                    for (k, v) in dict.iter() {
                        if let (Ok(k_str), Ok(v_str)) = (k.extract::<String>(), v.extract::<String>()) {
                            if let (Ok(h_name), Ok(h_val)) = (
                                HeaderName::from_bytes(k_str.as_bytes()),
                                HeaderValue::from_str(&v_str),
                            ) {
                                headers_map.insert(h_name, h_val);
                            }
                        }
                    }
                }
            }

            builder = builder.headers(headers_map);

            // 设置参数：GET 用 query，POST/PUT/PATCH 用 JSON body
            if let Some(params_dict) = &params {
                if let Ok(dict) = params_dict.as_ref(py).downcast::<PyDict>() {
                    if let Ok(json_value) = py_to_json(py, dict) {
                        match method {
                            reqwest::Method::GET | reqwest::Method::DELETE => {
                                if let Some(obj) = json_value.as_object() {
                                    let mut query_params = Vec::new();
                                    for (k, v) in obj {
                                        query_params.push((k.as_str(), v.to_string()));
                                    }
                                    builder = builder.query(&query_params);
                                }
                            }
                            _ => {
                                builder = builder.json(&json_value);
                            }
                        }
                    }
                }
            }

            builder
        });

        // 发起请求
        let request_timeout = Duration::from_secs_f64(timeout.unwrap_or(30.0).max(3.0));
        let tag = tag.unwrap_or_else(|| "single-req".to_string());
        let request_to_send = builder.try_clone().unwrap().build().unwrap();

        match tokio::time::timeout(request_timeout, builder.send()).await {
            Ok(Ok(res)) => {
                let status = res.status();
                result.insert("http_status".to_string(), status.as_u16().to_string());

                let headers = res.headers().clone();
                let text = res.text().await.unwrap_or_else(|e| format!("Failed to read response text: {}", e));

                debug_log(&tag, &request_to_send, status, &headers, &text);

                if !status.is_success() {
                    // 状态码非 2xx，构造异常
                    let mut exc = serde_json::Map::new();
                    exc.insert("type".to_string(), Value::String("HttpStatusError".to_string()));
                    exc.insert("message".to_string(), Value::String(format!("HTTP status error: {}", status.as_u16())));
                    result.insert("exception".to_string(), Value::Object(exc).to_string());
                } else {
                    result.insert("exception".to_string(), "{}".to_string());
                    result.insert("response".to_string(), text);
                }
            }
            Ok(Err(e)) => {
                result.insert("http_status".to_string(), "0".to_string());
                let mut exc = serde_json::Map::new();
                exc.insert("type".to_string(), Value::String("HttpError".to_string()));
                exc.insert("message".to_string(), Value::String(format!("Request error: {}", e)));
                result.insert("exception".to_string(), Value::Object(exc).to_string());
            }
            Err(_) => {
                result.insert("http_status".to_string(), "0".to_string());
                let err_msg = format!("Request timeout after {:.2} seconds", request_timeout.as_secs_f64());
                let mut exc = serde_json::Map::new();
                exc.insert("type".to_string(), Value::String("Timeout".to_string()));
                exc.insert("message".to_string(), Value::String(err_msg));
                result.insert("exception".to_string(), Value::Object(exc).to_string());
            }
        }

        // 记录 meta 信息
        let end = SystemTime::now();
        let process_time = end.duration_since(start)
            .unwrap_or(Duration::from_secs(0))
            .as_secs_f64();
        let start_str = format_datetime(start);
        let end_str = format_datetime(end);

        let mut meta = serde_json::Map::new();
        meta.insert("request_time".to_string(), Value::String(format!("{} -> {}", start_str, end_str)));
        meta.insert("process_time".to_string(), Value::String(format!("{:.4}", process_time)));
        meta.insert("tag".to_string(), Value::String(tag));
        result.insert("meta".to_string(), Value::Object(meta).to_string());

        // 转换为 Python 字典
        Python::with_gil(|py| -> PyResult<Py<PyAny>> {
            let dict = PyDict::new(py);

            dict.set_item("response", &result["response"])?;

            if let Some(http_status_str) = result.get("http_status") {
                if let Ok(http_status_int) = http_status_str.parse::<u16>() {
                    dict.set_item("http_status", http_status_int)?;
                } else {
                    dict.set_item("http_status", http_status_str)?;
                }
            }

            let meta_json_str = result.get("meta").map(|s| s.as_str()).unwrap_or("{}");
            let meta_pyobj = py.import("json")?.call_method1("loads", (meta_json_str,))?;
            dict.set_item("meta", meta_pyobj)?;

            if let Some(exc_str) = result.get("exception") {
                let exc_obj = py.import("json")?.call_method1("loads", (exc_str,))?;
                dict.set_item("exception", exc_obj)?;
            }

            Ok(dict.into_py(py))
        })
    })
}

#[pyfunction]
fn fetch_requests<'py>(
    py: Python<'py>,
    requests: Vec<RequestItem>,
    total_timeout: Option<f64>,
    mode: Option<ConcurrencyMode>,  // 新增参数
) -> PyResult<&'py PyAny> {
    pyo3_asyncio::tokio::future_into_py(py, async move {
        let total_duration = Duration::from_secs_f64(total_timeout.unwrap_or(30.0));
        let mode = mode.unwrap_or(ConcurrencyMode::SelectAll);
        let client = GLOBAL_CLIENT.lock().await.clone();

        let final_results = match mode {
            ConcurrencyMode::SelectAll => {
                execute_with_select_all(requests, total_duration, client).await
            }
            ConcurrencyMode::JoinAll => {
                execute_with_join_all(requests, total_duration, client).await
            }
        };

        // 转换为 Python 字典
        convert_results_to_python(final_results)
    })
}

fn format_datetime(time: SystemTime) -> String {
    let datetime: DateTime<Local> = time.into();
    datetime.format("%Y-%m-%d %H:%M:%S").to_string()
}

#[pymodule]
fn rusty_req(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<RequestItem>()?;
    m.add_class::<ConcurrencyMode>()?;
    m.add_function(wrap_pyfunction!(fetch_requests, m)?)?;
    m.add_function(wrap_pyfunction!(fetch_single, m)?)?;
    m.add_function(wrap_pyfunction!(set_debug, m)?)?;
    Ok(())
}