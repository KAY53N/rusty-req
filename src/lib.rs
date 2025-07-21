use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::collections::HashMap;
use reqwest::Client;
use std::time::{Duration, SystemTime};
use futures::future::join_all;
use serde_json::Value;
use chrono::{DateTime, Local};
use once_cell::sync::Lazy;
use tokio::sync::Mutex;


// 全局共享的HTTP客户端
static GLOBAL_CLIENT: Lazy<Mutex<Client>> = Lazy::new(|| {
    Mutex::new(Client::builder()
        .timeout(Duration::from_secs(30))
        .build()
        .expect("Failed to create HTTP client"))
});

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
    pub tag: Option<String>, // ✅ 新增字段
}

#[pymethods]
impl RequestItem {
    #[new]
    fn new(
        url: String,
        method: Option<String>,
        params: Option<Py<PyDict>>,
        timeout: Option<f64>,
        tag: Option<String>, // ✅ 新增字段
    ) -> Self {
        Self { url, method, params, timeout, tag }
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

#[pyfunction]
fn fetch_requests<'py>(
    py: Python<'py>,
    requests: Vec<RequestItem>,
    total_timeout: Option<f64>
) -> PyResult<&'py PyAny> {
    pyo3_asyncio::tokio::future_into_py(py, async move {
        let total_duration = Duration::from_secs_f64(total_timeout.unwrap_or(30.0));
        let client = GLOBAL_CLIENT.lock().await.clone();

        let request_futures = requests.iter().map(|req| {
            let client = client.clone();
            let req = req.clone();
            async move {
                let mut result = HashMap::new();
                result.insert("response".to_string(), String::new());
                result.insert("error".to_string(), String::new());

                let start = SystemTime::now();

                // 构建请求
                let builder = Python::with_gil(|py| -> reqwest::RequestBuilder {
                    let mut builder = client.request(
                        req.method.as_deref().unwrap_or("POST").parse().unwrap(),
                        &req.url
                    );

                    if let Some(params_dict) = &req.params {
                        if let Ok(dict) = params_dict.as_ref(py).downcast::<PyDict>() {
                            if let Ok(json_value) = py_to_json(py, dict) {
                                builder = builder.json(&json_value);
                            }
                        }
                    }
                    builder
                });

                // 发起请求，使用单个请求超时控制
                let timeout = Duration::from_secs_f64(req.timeout.unwrap_or(5.0).max(5.0));
                match tokio::time::timeout(timeout, builder.send()).await {
                    Ok(Ok(res)) => {
                        if let Ok(text) = res.text().await {
                            result.insert("response".to_string(), text);
                        }
                    },
                    Ok(Err(e)) => {
                        result.insert("error".to_string(), format!("Request error: {}", e));
                    },
                    Err(_) => {
                        result.insert("error".to_string(), "Request timeout".to_string());
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
                meta.insert("requestTime".to_string(), Value::String(format!("{} -> {}", start_str, end_str)));
                meta.insert("processTime".to_string(), Value::String(format!("{:.4}", process_time)));
                if let Some(tag) = req.tag.clone() {
                    meta.insert("tag".to_string(), Value::String(tag));
                }

                result.insert("meta".to_string(), Value::Object(meta).to_string());

                result
            }
        });

        // 并发请求 + 全局超时控制
        let results = match tokio::time::timeout(total_duration, join_all(request_futures)).await {
            Ok(results) => results,
            Err(_) => {
                // 超时则返回带错误信息的结构
                requests.iter().map(|req| {
                    let mut res = HashMap::new();
                    res.insert("response".to_string(), String::new());
                    res.insert("error".to_string(), "TOTAL_OPERATION_TIMEOUT".to_string());

                    let mut meta = serde_json::Map::new();
                    meta.insert("requestTime".to_string(), Value::String("".to_string()));
                    meta.insert("processTime".to_string(), Value::String("0.0000".to_string()));
                    if let Some(tag) = req.tag.clone() {
                        meta.insert("tag".to_string(), Value::String(tag));
                    }
                    res.insert("meta".to_string(), Value::Object(meta).to_string());
                    res
                }).collect()
            }
        };

        // 转换为 Python 字典
        Python::with_gil(|py| {
            results.into_iter().map(|res| {
                let dict = PyDict::new(py);

                // 这里不调用 as_str()
                dict.set_item("response", &res["response"])?;
                dict.set_item("error", &res["error"])?;

                // 这里用 get + map 保证安全，res.get("meta") -> Option<&String>
                let meta_json_str = res.get("meta").map(|s| s.as_str()).unwrap_or("{}");

                let meta_pyobj = py
                    .import("json")?
                    .call_method1("loads", (meta_json_str,))?;

                dict.set_item("meta", meta_pyobj)?;

                Ok(dict.into_py(py))
            }).collect::<PyResult<Vec<Py<PyAny>>>>()
        })
    })
}


fn format_datetime(time: SystemTime) -> String {
    let datetime: DateTime<Local> = time.into();
    datetime.format("%Y-%m-%d %H:%M:%S").to_string()
}

#[pymodule]
fn rust_http_client(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<RequestItem>()?;
    m.add_function(wrap_pyfunction!(fetch_requests, m)?)?;
    Ok(())
}