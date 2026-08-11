use std::collections::HashMap;
use std::time::Duration;
use crate::request::RequestItem;
use crate::request::executor::execute_single_request;
use futures::future::join_all;
use pyo3::{pyclass, pymethods};
use reqwest::Client;

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

/// Shape expected by `fetch_requests` when converting results to Python dicts.
/// A bare `http_status` map panics on `res["response"]` under load (high N).
fn global_timeout_result(tag: Option<String>, total_secs: f64) -> HashMap<String, String> {
    let mut timeout_result = HashMap::new();
    timeout_result.insert("http_status".to_string(), "0".to_string());
    timeout_result.insert(
        "response".to_string(),
        serde_json::json!({"headers":{}, "content":""}).to_string(),
    );
    let mut exc = serde_json::Map::new();
    exc.insert("type".to_string(), serde_json::Value::String("GlobalTimeout".to_string()));
    exc.insert(
        "message".to_string(),
        serde_json::Value::String(format!(
            "Request cancelled by total_timeout after {:.2} seconds",
            total_secs
        )),
    );
    timeout_result.insert("exception".to_string(), serde_json::Value::Object(exc).to_string());
    let mut meta = serde_json::Map::new();
    meta.insert(
        "process_time".to_string(),
        serde_json::Value::String(format!("{:.4}", total_secs)),
    );
    if let Some(t) = tag {
        meta.insert("tag".to_string(), serde_json::Value::String(t));
    }
    timeout_result.insert("meta".to_string(), serde_json::Value::Object(meta).to_string());
    timeout_result
}

pub async fn execute_with_select_all(
    requests: Vec<RequestItem>,
    total_duration: Duration,
    base_client: Option<Client>,
) -> Vec<HashMap<String, String>> {
    let total_secs = total_duration.as_secs_f64();
    let futures = requests.into_iter().map(|req| {
        let client = base_client.clone();
        let tag = req.tag.clone();
        async move {
            match tokio::time::timeout(total_duration, execute_single_request(req, client)).await {
                Ok(result) => result,
                Err(_) => global_timeout_result(tag, total_secs),
            }
        }
    });

    join_all(futures).await
}

pub async fn execute_with_join_all(
    requests: Vec<RequestItem>,
    total_duration: Duration,
    base_client: Option<Client>,
) -> Vec<HashMap<String, String>> {
    let mut results = Vec::with_capacity(requests.len());
    let total_secs = total_duration.as_secs_f64();

    for req in requests {
        let tag = req.tag.clone();
        match tokio::time::timeout(total_duration, execute_single_request(req, base_client.clone())).await {
            Ok(result) => results.push(result),
            Err(_) => results.push(global_timeout_result(tag, total_secs)),
        }
    }

    results
}
