use std::collections::HashMap;
use std::time::{Duration, SystemTime};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use pyo3_asyncio::generic::future_into_py;
use reqwest::{Client, Proxy, StatusCode};
use crate::request::{execute_with_join_all, execute_with_select_all, RequestItem};
use crate::network::{ProxyConfig, HttpVersion};
use serde_json::Value;
use url::Url;
use crate::{ConcurrencyMode, GLOBAL_CLIENT, GLOBAL_PROXY};
use crate::debug::debug_log;
use crate::utils::{format_datetime, py_to_json};


pub(crate) async fn create_client_with_proxy(
    url: &str,
    proxy_config: &ProxyConfig,
    http_version: &HttpVersion,
) -> Result<Client, Box<dyn std::error::Error>> {
    let mut builder = Client::builder()
        .timeout(Duration::from_secs(30))
        .gzip(true)
        .brotli(true)
        .deflate(true)
        .user_agent("Rust/1.88.0 (6b00bc388) reqwest/0.11.27");

    builder = http_version.apply_to_builder(builder);

    if let Some(all_proxy) = &proxy_config.all {
        let proxy_url = match (&proxy_config.username, &proxy_config.password) {
            (Some(user), Some(pass)) => {
                let mut url_parsed = Url::parse(all_proxy)?;
                let _ = url_parsed.set_username(user);
                let _ = url_parsed.set_password(Some(pass));
                url_parsed.to_string()
            }
            (Some(user), None) => {
                let mut url_parsed = Url::parse(all_proxy)?;
                let _ = url_parsed.set_username(user);
                url_parsed.to_string()
            }
            _ => all_proxy.clone(),
        };
        builder = builder.proxy(Proxy::all(&proxy_url)?);
    } else {
        let parsed = Url::parse(url)?;
        match parsed.scheme() {
            "http" => {
                if let Some(http_proxy) = &proxy_config.http {
                    builder = builder.proxy(Proxy::http(http_proxy)?);
                }
            }
            "https" => {
                if let Some(https_proxy) = &proxy_config.https {
                    builder = builder.proxy(Proxy::https(https_proxy)?);
                }
            }
            _ => {}
        }
    }

    Ok(builder.build()?)
}

pub async fn execute_single_request(req: RequestItem, base_client: Option<Client>) -> HashMap<String, String> {
    let mut result = HashMap::new();
    result.insert("response".to_string(), String::new());

    let start = SystemTime::now();
    let http_version = req.http_version.clone().unwrap_or(HttpVersion::Auto);

    let proxy_config = if req.proxy.is_some() { req.proxy.clone() } else { GLOBAL_PROXY.lock().await.clone() };

    let client = if let Some(proxy_config) = &proxy_config {
        match create_client_with_proxy(&req.url, proxy_config, &http_version).await {
            Ok(client) => client,
            Err(e) => {
                result.insert("http_status".to_string(), "0".to_string());
                let mut exc = serde_json::Map::new();
                exc.insert("type".to_string(), Value::String("ProxyError".to_string()));
                exc.insert("message".to_string(), Value::String(format!("Proxy configuration error: {}", e)));
                result.insert("exception".to_string(), Value::Object(exc).to_string());

                let mut meta = serde_json::Map::new();
                meta.insert("request_time".to_string(), Value::String("".to_string()));
                meta.insert("process_time".to_string(), Value::String("0.0000".to_string()));
                if let Some(tag) = req.tag.clone() { meta.insert("tag".to_string(), Value::String(tag)); }
                result.insert("meta".to_string(), Value::Object(meta).to_string());
                return result;
            }
        }
    } else if let Some(client) = base_client { client }
    else { GLOBAL_CLIENT.lock().await.clone() };

    let method = req.method.clone().unwrap_or_else(|| "GET".to_string()).to_uppercase();
    let method = method.parse::<reqwest::Method>().unwrap_or(reqwest::Method::GET);

    let mut request_builder = client.request(method.clone(), &req.url);
    let timeout = Duration::from_secs_f64(req.timeout.unwrap_or(30.0).max(3.0));
    request_builder = request_builder.timeout(timeout);

    // headers
    let mut headers_to_add = Vec::new();
    if let Some(py_headers) = &req.headers {
        Python::with_gil(|py| {
            if let Ok(dict) = py_headers.as_ref(py).downcast::<PyDict>() {
                for (k, v) in dict.iter() {
                    if let (Ok(k_str), Ok(v_str)) = (k.extract::<String>(), v.extract::<String>()) {
                        if let (Ok(h_name), Ok(h_val)) = (
                            reqwest::header::HeaderName::from_bytes(k_str.as_bytes()),
                            reqwest::header::HeaderValue::from_str(&v_str),
                        ) { headers_to_add.push((h_name, h_val)); }
                    }
                }
            }
        });
    }
    for (name, value) in headers_to_add { request_builder = request_builder.header(name, value); }

    if let Some(params_dict) = &req.params {
        request_builder = Python::with_gil(|py| {
            let mut inner_request_builder = request_builder;
            if let Ok(dict) = params_dict.as_ref(py).downcast::<PyDict>() {
                if let Ok(json) = py_to_json(py, dict) {
                    match method {
                        reqwest::Method::GET | reqwest::Method::DELETE => {
                            if let Some(obj) = json.as_object() {
                                let query_pairs: Vec<(String, String)> = obj.iter()
                                    .map(|(k, v)| (k.clone(), v.to_string().trim_matches('"').to_string()))
                                    .collect();
                                let query_refs: Vec<(&str, &str)> = query_pairs.iter().map(|(k,v)| (k.as_str(), v.as_str())).collect();
                                inner_request_builder = inner_request_builder.query(&query_refs);
                            }
                        }
                        _ => { inner_request_builder = inner_request_builder.json(&json); }
                    }
                }
            }
            inner_request_builder
        });
    }

    let tag = req.tag.clone().unwrap_or_else(|| "no-tag".to_string());

    match tokio::time::timeout(timeout, request_builder.send()).await {
        Ok(Ok(res)) => {
            let status = res.status();
            result.insert("http_status".to_string(), status.as_u16().to_string());

            // 生成 headers_map
            let headers_map: serde_json::Map<String, Value> = res.headers().iter()
                .map(|(k, v)| (k.to_string(), Value::String(v.to_str().unwrap_or("").to_string())))
                .collect();

            // 读取响应
            let text = res.text().await.unwrap_or_else(|e| format!("Failed to read response text: {}", e));

            // response 对象
            let response = serde_json::json!({
                "headers": headers_map,
                "content": text
            });

            // 插入 result
            result.insert("response".to_string(), response.to_string());

            // debug_log 调用
            debug_log(
                &method.to_string(),
                &tag,
                &req.url,
                status,
                &headers_map,
                &response,
                proxy_config.as_ref().and_then(|p| p.all.as_deref()),
                proxy_config.as_ref().and_then(|p| {
                    if p.username.is_some() {
                        Some("with authentication")
                    } else {
                        None
                    }
                }).map(|s| s),
            );

            if !status.is_success() {
                let mut exc = serde_json::Map::new();
                exc.insert("type".to_string(), Value::String("HttpStatusError".to_string()));
                exc.insert("message".to_string(), Value::String(format!("HTTP status error: {}", status.as_u16())));
                result.insert("exception".to_string(), Value::Object(exc).to_string());
            } else {
                result.insert("exception".to_string(), "{}".to_string());
            }
        }
        Ok(Err(e)) => {
            result.insert("http_status".to_string(), "0".to_string());
            let mut exc = serde_json::Map::new();
            exc.insert("type".to_string(), Value::String("HttpError".to_string()));
            exc.insert("message".to_string(), Value::String(format!("Request error: {}", e)));
            result.insert("exception".to_string(), Value::Object(exc).to_string());
            result.insert("response".to_string(), serde_json::json!({"headers":{}, "content":""}).to_string());
        }
        Err(_) => {
            result.insert("http_status".to_string(), "0".to_string());
            let mut exc = serde_json::Map::new();
            exc.insert("type".to_string(), Value::String("Timeout".to_string()));
            exc.insert("message".to_string(), Value::String(format!("Request timeout after {:.2} seconds", timeout.as_secs_f64())));
            result.insert("exception".to_string(), Value::Object(exc).to_string());
            result.insert("response".to_string(), serde_json::json!({"headers":{}, "content":""}).to_string());
        }
    }

    // meta 信息
    let end = SystemTime::now();
    let process_time = end.duration_since(start).unwrap_or(Duration::from_secs(0)).as_secs_f64();
    let start_str = format_datetime(start);
    let end_str = format_datetime(end);
    let mut meta = serde_json::Map::new();
    meta.insert("request_time".to_string(), Value::String(format!("{} -> {}", start_str, end_str)));
    meta.insert("process_time".to_string(), Value::String(format!("{:.4}", process_time)));
    if let Some(tag) = req.tag.clone() { meta.insert("tag".to_string(), Value::String(tag)); }
    result.insert("meta".to_string(), Value::Object(meta).to_string());

    result
}

#[pyfunction]
pub fn fetch_single<'py>(
    py: Python<'py>,
    url: String,
    method: Option<String>,
    params: Option<Py<PyDict>>,
    timeout: Option<f64>,
    headers: Option<Py<PyDict>>,
    tag: Option<String>,
    proxy: Option<ProxyConfig>,
    http_version: Option<HttpVersion>,
) -> PyResult<&'py PyAny> {
    // 这里直接调用 execute_single_request 异步包装
    pyo3_asyncio::tokio::future_into_py(py, async move {
        let req = RequestItem { url, method, params, timeout, tag, headers, proxy, http_version };
        let result = execute_single_request(req, None).await;
        Python::with_gil(|py| -> PyResult<Py<PyAny>> {
            let dict = PyDict::new(py);
            dict.set_item("response", &result["response"])?;
            dict.set_item("http_status", result.get("http_status").unwrap_or(&"0".to_string()))?;
            dict.set_item("meta", result.get("meta").unwrap_or(&"{}".to_string()))?;
            dict.set_item("exception", result.get("exception").unwrap_or(&"{}".to_string()))?;
            Ok(dict.into_py(py))
        })
    })
}

/// 异步批量请求函数
#[pyfunction]
pub fn fetch_requests<'py>(
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

        Python::with_gil(|py| -> PyResult<PyObject> {
            let py_list = PyList::empty(py);
            for res in final_results {
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

                py_list.append(dict)?;
            }
            Ok(py_list.into_py(py))
        })
    })
}
