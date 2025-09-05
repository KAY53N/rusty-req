#![allow(non_local_definitions)]
use pyo3::{pyclass, pymethods, pyfunction, pymodule, PyResult, Python, Py, wrap_pyfunction, PyAny, IntoPy};
use pyo3::types::{PyDict, PyList};
use std::collections::HashMap;
use reqwest::{Client, StatusCode, Proxy, header::{HeaderMap}};
use std::time::{Duration, SystemTime};
use futures::stream::{FuturesUnordered, StreamExt};
use serde_json::Value;
use chrono::{DateTime, Local};
use once_cell::sync::Lazy;
use tokio::sync::Mutex;
use std::path::Path;
use std::sync::RwLock;
use std::io::Write;
use futures::future::join_all;
use std::fs::OpenOptions;
use url::Url;


// Debug 配置
#[derive(Clone)]
enum DebugTarget {
    Console,
    File(String),
}

#[derive(Clone)]
struct DebugConfig {
    enabled: bool,
    target: DebugTarget,
}

static DEBUG_CONFIG: Lazy<RwLock<DebugConfig>> = Lazy::new(|| {
    RwLock::new(DebugConfig {
        enabled: false,
        target: DebugTarget::Console,
    })
});

const DEFAULT_USER_AGENT: &str = "Rust/1.88.0 (6b00bc388) reqwest/0.11.27";

static GLOBAL_CLIENT: Lazy<Mutex<Client>> = Lazy::new(|| {
    Mutex::new(Client::builder()
        .timeout(Duration::from_secs(30))
        .gzip(true)
        .brotli(true)
        .deflate(true)
        .user_agent(DEFAULT_USER_AGENT)
        .build()
        .expect("Failed to create HTTP client"))
});

static GLOBAL_PROXY: Lazy<Mutex<Option<ProxyConfig>>> = Lazy::new(|| Mutex::new(None));

#[pyclass]
#[derive(Clone)]
pub struct ProxyConfig {
    #[pyo3(get, set)]
    pub http: Option<String>,
    #[pyo3(get, set)]
    pub https: Option<String>,
    #[pyo3(get, set)]
    pub all: Option<String>,
    #[pyo3(get, set)]
    pub no_proxy: Option<Vec<String>>,
}

#[pyclass]
#[derive(Clone, PartialEq)]
pub enum ConcurrencyMode {
    #[pyo3(name = "SELECT_ALL")]
    SelectAll,
    #[pyo3(name = "JOIN_ALL")]
    JoinAll,
}

#[pymethods]
impl ProxyConfig {
    #[new]
    fn new(http: Option<String>, https: Option<String>, all: Option<String>, no_proxy: Option<Vec<String>>) -> Self {
        Self { http, https, all, no_proxy }
    }
    #[staticmethod]
    fn from_url(proxy_url: String) -> Self {
        Self { http: None, https: None, all: Some(proxy_url), no_proxy: None }
    }
    #[staticmethod]
    fn from_dict(http: Option<String>, https: Option<String>) -> Self {
        Self { http, https, all: None, no_proxy: None }
    }
}

#[pymethods]
impl ConcurrencyMode {
    #[new]
    fn new() -> Self { ConcurrencyMode::SelectAll }
    #[classattr]
    const SELECT_ALL: ConcurrencyMode = ConcurrencyMode::SelectAll;
    #[classattr]
    const JOIN_ALL: ConcurrencyMode = ConcurrencyMode::JoinAll;
    fn __str__(&self) -> String {
        match self { ConcurrencyMode::SelectAll => "SELECT_ALL".to_string(), ConcurrencyMode::JoinAll => "JOIN_ALL".to_string() }
    }
    fn __repr__(&self) -> String { format!("ConcurrencyMode.{}", self.__str__()) }
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
    #[pyo3(get, set)]
    pub proxy: Option<ProxyConfig>,
}

#[pymethods]
impl RequestItem {
    #[new]
    fn new(url: String, method: Option<String>, params: Option<Py<PyDict>>, timeout: Option<f64>, tag: Option<String>, headers: Option<Py<PyDict>>, proxy: Option<ProxyConfig>) -> Self {
        Self { url, method, params, timeout, tag, headers, proxy }
    }
}

#[pyfunction]
fn set_debug(enabled: bool, target: Option<String>) {
    let mut cfg = DEBUG_CONFIG.write().unwrap();
    cfg.enabled = enabled;

    if let Some(t) = target {
        if t.to_lowercase() == "console" || t.is_empty() {
            cfg.target = DebugTarget::Console;
        } else {
            let path = Path::new(&t);
            if path.is_dir() {
                let file_path = path.join("debug.log");
                cfg.target = DebugTarget::File(file_path.to_string_lossy().into_owned());
            } else {
                cfg.target = DebugTarget::File(t);
            }
        }
    } else {
        cfg.target = DebugTarget::Console; // 默认
    }
}

pub fn is_debug() -> bool {
    DEBUG_CONFIG.read().unwrap().enabled
}

fn debug_output(message: &str) {
    let cfg = DEBUG_CONFIG.read().unwrap();
    match &cfg.target {
        DebugTarget::Console => {
            println!("{}", message);
        }
        DebugTarget::File(path) => {
            if let Ok(mut file) = OpenOptions::new()
                .create(true)
                .append(true)
                .open(path)
            {
                let _ = writeln!(file, "{}", message);
            }
        }
    }
}

pub fn debug_log(
    method: &str,
    tag: &str,
    url: &str,
    status: StatusCode,
    headers: &HeaderMap,
    body: &str,
    proxy: Option<&str>,
) {
    if !is_debug() {
        return;
    }

    let now = Local::now().format("%Y-%m-%d %H:%M:%S").to_string();

    let mut msg = String::new();
    msg.push_str(&format!("\n================== [DEBUG: {}] ==================\n", tag));
    msg.push_str(&format!("Time           : {}\n", now));
    msg.push_str(&format!("Method         : {}\n", method));
    msg.push_str(&format!("Request URL    : {}\n", url));
    msg.push_str(&format!("Response Status: {}\n", status));
    if let Some(p) = proxy {
        msg.push_str(&format!("Proxy          : {}\n", p));
    } else {
        msg.push_str("Proxy          : (none)\n");
    }
    msg.push_str(&format!("Headers        : {:?}\n", headers));
    msg.push_str(&format!("Body:\n{}\n", body));
    msg.push_str("==================================================\n");

    debug_output(&msg);
}

fn should_use_proxy(url: &str, no_proxy: &Option<Vec<String>>) -> bool {
    if let Some(list) = no_proxy {
        if let Ok(parsed) = Url::parse(url) {
            if let Some(host) = parsed.host_str() {
                for pattern in list {
                    if host.contains(pattern) || pattern == "*" { return false; }
                }
            }
        }
    }
    true
}

async fn create_client_with_proxy(url: &str, proxy_config: &ProxyConfig) -> Result<Client, Box<dyn std::error::Error>> {
    let mut builder = Client::builder()
        .timeout(Duration::from_secs(30))
        .gzip(true)
        .brotli(true)
        .deflate(true)
        .user_agent(DEFAULT_USER_AGENT);

    if should_use_proxy(url, &proxy_config.no_proxy) {
        if let Some(all) = &proxy_config.all {
            builder = builder.proxy(Proxy::all(all)?);
        } else {
            let parsed = Url::parse(url)?;
            match parsed.scheme() {
                "http" => { if let Some(p) = &proxy_config.http { builder = builder.proxy(Proxy::http(p)?); } }
                "https" => { if let Some(p) = &proxy_config.https { builder = builder.proxy(Proxy::https(p)?); } }
                _ => {}
            }
        }
    }
    Ok(builder.build()?)
}

fn py_to_json(py: Python, obj: &PyAny) -> PyResult<Value> {
    if let Ok(b) = obj.extract::<bool>() { return Ok(Value::Bool(b)); }
    if let Ok(s) = obj.extract::<String>() { return Ok(Value::String(s)); }
    if let Ok(i) = obj.extract::<i64>() { return Ok(Value::Number(i.into())); }
    if let Ok(f) = obj.extract::<f64>() { return Ok(Value::Number(serde_json::Number::from_f64(f).unwrap_or(0.into()))); }
    if let Ok(list) = obj.downcast::<PyList>() {
        let mut vec = Vec::new();
        for i in list.iter() { vec.push(py_to_json(py, i)?); }
        return Ok(Value::Array(vec));
    }
    if let Ok(dict) = obj.downcast::<PyDict>() {
        let mut map = serde_json::Map::new();
        for (k,v) in dict.iter() { map.insert(k.to_string(), py_to_json(py, v)?); }
        return Ok(Value::Object(map));
    }
    Ok(Value::String(obj.to_string()))
}

fn create_global_timeout_result(req: &RequestItem) -> HashMap<String, String> {
    let mut r = HashMap::new();
    r.insert("http_status".to_string(), "0".to_string());
    r.insert("response".to_string(), "".to_string());
    let mut exc = serde_json::Map::new();
    exc.insert("type".to_string(), Value::String("GlobalTimeout".to_string()));
    exc.insert("message".to_string(), Value::String("Request timed out due to global timeout".to_string()));
    r.insert("exception".to_string(), Value::Object(exc).to_string());
    let mut meta = serde_json::Map::new();
    meta.insert("request_time".to_string(), Value::String("".to_string()));
    meta.insert("process_time".to_string(), Value::String("0.0000".to_string()));
    if let Some(tag) = &req.tag { meta.insert("tag".to_string(), Value::String(tag.clone())); }
    r.insert("meta".to_string(), Value::Object(meta).to_string());
    r
}

async fn execute_single_request(
    req: RequestItem,
    base_client: Option<Client>  // 可选的基础客户端
) -> HashMap<String, String> {
    let mut result = HashMap::new();
    result.insert("response".to_string(), String::new());

    let start = SystemTime::now();

    // 确定代理配置：请求级别 > 全局级别
    let proxy_config = if req.proxy.is_some() {
        req.proxy.clone()
    } else {
        GLOBAL_PROXY.lock().await.clone()
    };

    // 创建客户端（考虑代理）
    let client = if let Some(proxy_config) = &proxy_config {
        match create_client_with_proxy(&req.url, proxy_config).await {
            Ok(client) => client,
            Err(e) => {
                result.insert("http_status".to_string(), "0".to_string());
                let mut exc = serde_json::Map::new();
                exc.insert("type".to_string(), Value::String("ProxyError".to_string()));
                exc.insert(
                    "message".to_string(),
                    Value::String(format!("Proxy configuration error: {}", e)),
                );
                result.insert("exception".to_string(), Value::Object(exc).to_string());

                let mut meta = serde_json::Map::new();
                meta.insert("request_time".to_string(), Value::String("".to_string()));
                meta.insert("process_time".to_string(), Value::String("0.0000".to_string()));
                if let Some(tag) = req.tag.clone() {
                    meta.insert("tag".to_string(), Value::String(tag));
                }
                result.insert("meta".to_string(), Value::Object(meta).to_string());
                return result;
            }
        }
    } else if let Some(client) = base_client {
        client
    } else {
        // 这里直接在 async 函数中 await
        GLOBAL_CLIENT.lock().await.clone()
    };

    // 构建请求方法
    let method = req.method.clone().unwrap_or_else(|| "GET".to_string()).to_uppercase();
    let method = method.parse::<reqwest::Method>().unwrap_or(reqwest::Method::GET);
    let mut builder = client.request(method.clone(), &req.url);

    // 设置 Header
    let mut headers = reqwest::header::HeaderMap::new();
    headers.insert(reqwest::header::ACCEPT_ENCODING, reqwest::header::HeaderValue::from_static("gzip, deflate, br"));

    // Python 头部转换
    if let Some(py_headers) = &req.headers {
        Python::with_gil(|py| {
            if let Ok(dict) = py_headers.as_ref(py).downcast::<PyDict>() {
                for (k, v) in dict.iter() {
                    if let (Ok(k_str), Ok(v_str)) = (k.extract::<String>(), v.extract::<String>()) {
                        if let (Ok(h_name), Ok(h_val)) = (
                            reqwest::header::HeaderName::from_bytes(k_str.as_bytes()),
                            reqwest::header::HeaderValue::from_str(&v_str),
                        ) {
                            headers.insert(h_name, h_val);
                        }
                    }
                }
            }
        });
    }
    builder = builder.headers(headers);

    // 设置参数
    if let Some(params_dict) = &req.params {
        let mut query: Option<Vec<(String, String)>> = None;
        let mut json_value: Option<serde_json::Value> = None;

        Python::with_gil(|py| {
            if let Ok(dict) = params_dict.as_ref(py).downcast::<PyDict>() {
                if let Ok(json) = py_to_json(py, dict) {
                    match method {
                        reqwest::Method::GET | reqwest::Method::DELETE => {
                            if let Some(obj) = json.as_object() {
                                // 克隆 key 和 value 到新的 Vec
                                query = Some(
                                    obj.iter()
                                        .map(|(k, v)| (k.clone(), v.to_string()))
                                        .collect()
                                );
                            }
                        }
                        _ => {
                            json_value = Some(json.clone());
                        }
                    }
                }
            }
        });

        // 在闭包外修改 builder
        if let Some(q) = query {
            // 注意这里需要转换成 &[(str, str)] 才能用 query
            let q_ref: Vec<(&str, &str)> = q.iter().map(|(k, v)| (k.as_str(), v.as_str())).collect();
            builder = builder.query(&q_ref);
        }
        if let Some(j) = json_value {
            builder = builder.json(&j);
        }
    }

    // 发起请求
    let timeout = Duration::from_secs_f64(req.timeout.unwrap_or(30.0).max(3.0));
    let tag = req.tag.clone().unwrap_or_else(|| "no-tag".to_string());
    let _request_to_send = builder.try_clone().unwrap().build().unwrap(); // 前面未使用警告，可加 `_` 忽略

    match tokio::time::timeout(timeout, builder.send()).await {
        Ok(Ok(res)) => {
            let status = res.status();
            result.insert("http_status".to_string(), status.as_u16().to_string());

            let headers = res.headers().clone();
            let text = res.text().await.unwrap_or_else(|e| format!("Failed to read response text: {}", e));

            debug_log(
                &method.to_string(),   // 请求方法
                &tag,                  // tag
                req.url.as_str(),      // URL
                status,                // 状态码
                &headers,              // 响应头
                &text,                 // 响应内容
                proxy_config.as_ref().and_then(|p| p.all.as_deref()),  // 使用的代理
            );

            if !status.is_success() {
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
            let mut exc = serde_json::Map::new();
            exc.insert("type".to_string(), Value::String("Timeout".to_string()));
            exc.insert("message".to_string(), Value::String(format!("Request timeout after {:.2} seconds", timeout.as_secs_f64())));
            result.insert("exception".to_string(), Value::Object(exc).to_string());
        }
    }

    // 填充 meta 信息
    let end = SystemTime::now();
    let process_time = end.duration_since(start).unwrap_or(Duration::from_secs(0)).as_secs_f64();
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


fn format_datetime(time: SystemTime) -> String {
    let datetime: DateTime<Local> = time.into();
    datetime.format("%Y-%m-%d %H:%M:%S").to_string()
}

async fn execute_with_select_all(
    requests: Vec<RequestItem>,
    total_duration: Duration,
    base_client: Option<Client>,
) -> Vec<HashMap<String, String>> {
    let total_requests = requests.len();
    let mut results = vec![None; total_requests];
    let mut futures = FuturesUnordered::new();

    // 克隆一份 requests 用于超时结果
    let requests_clone = requests.clone();

    for (i, req) in requests.into_iter().enumerate() {
        let client = base_client.clone();
        futures.push(async move {
            let res = execute_single_request(req, client).await;
            (i, res)
        });
    }

    // 流式收集结果
    let collection_task = async {
        while let Some((i, res)) = futures.next().await {
            results[i] = Some(res);
        }
    };

    // 带总超时
    let _ = tokio::time::timeout(total_duration, collection_task).await;

    // 填充未完成的请求
    results
        .into_iter()
        .enumerate()
        .map(|(i, r)| r.unwrap_or_else(|| create_global_timeout_result(&requests_clone[i])))
        .collect()
}

async fn execute_with_join_all(
    requests: Vec<RequestItem>,
    total_duration: Duration,
    base_client: Option<Client>,
) -> Vec<HashMap<String, String>> {
    let client = if let Some(base) = base_client {
        base
    } else {
        GLOBAL_CLIENT.lock().await.clone()
    };

    // 所有请求的 future
    let futures_vec = requests.iter().cloned().map(|req| {
        let client = client.clone();
        async move { execute_single_request(req, Some(client)).await }
    }).collect::<Vec<_>>();

    match tokio::time::timeout(total_duration, join_all(futures_vec)).await {
        Ok(results) => results,
        Err(_) => requests.iter().map(|req| create_global_timeout_result(req)).collect(),
    }
}

#[pyfunction]
fn fetch_requests<'py>(
    py: Python<'py>,
    requests: Vec<RequestItem>,
    total_timeout: Option<f64>,
    mode: Option<ConcurrencyMode>,
) -> PyResult<&'py PyAny> {
    pyo3_asyncio::tokio::future_into_py(py, async move {
        let total_duration = Duration::from_secs_f64(total_timeout.unwrap_or(30.0));
        let mode = mode.unwrap_or(ConcurrencyMode::SelectAll);
        let base_client = Some(GLOBAL_CLIENT.lock().await.clone());

        let final_results = match mode {
            ConcurrencyMode::SelectAll => {
                execute_with_select_all(requests, total_duration, base_client).await
            }
            ConcurrencyMode::JoinAll => {
                execute_with_join_all(requests, total_duration, base_client).await
            }
        };

        // 转换为 Python 字典列表
        Python::with_gil(|py| -> PyResult<Vec<Py<PyAny>>> {
            final_results.into_iter().map(|res| {
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
    proxy: Option<ProxyConfig>,
) -> PyResult<&'py PyAny> {
    pyo3_asyncio::tokio::future_into_py(py, async move {
        // 请求对象
        let req = RequestItem {
            url,
            method,
            params,
            timeout,
            tag,
            headers,
            proxy,
        };

        // 调用 execute_single_request
        let result = execute_single_request(req, None).await;

        // 转换为 Python dict
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

            // meta 转 Python 对象
            let meta_json_str = result.get("meta").map(|s| s.as_str()).unwrap_or("{}");
            let meta_pyobj = py.import("json")?.call_method1("loads", (meta_json_str,))?;
            dict.set_item("meta", meta_pyobj)?;

            // exception 转 Python 对象
            let exc_str = result.get("exception").map(|s| s.as_str()).unwrap_or("{}");
            let exc_pyobj = py.import("json")?.call_method1("loads", (exc_str,))?;
            dict.set_item("exception", exc_pyobj)?;

            Ok(dict.into_py(py))
        })
    })
}

#[pyfunction]
fn set_global_proxy<'py>(py: Python<'py>, proxy: Option<ProxyConfig>) -> PyResult<&'py PyAny> {
    pyo3_asyncio::tokio::future_into_py(py, async move {
        let mut g = GLOBAL_PROXY.lock().await;
        *g = proxy;
        Ok(())
    })
}

#[pymodule]
fn rusty_req(_py: Python, m: &pyo3::types::PyModule) -> PyResult<()> {
    m.add_class::<RequestItem>()?;
    m.add_class::<ProxyConfig>()?;
    m.add_class::<ConcurrencyMode>()?;
    m.add_function(wrap_pyfunction!(fetch_requests, m)?)?;
    m.add_function(wrap_pyfunction!(fetch_single, m)?)?;
    m.add_function(wrap_pyfunction!(set_global_proxy, m)?)?;
    m.add_function(wrap_pyfunction!(set_debug, m)?)?;
    Ok(())
}
