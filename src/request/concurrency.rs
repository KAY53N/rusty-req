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

pub async fn execute_with_select_all(
    requests: Vec<RequestItem>,
    total_duration: Duration,
    base_client: Option<Client>,
) -> Vec<HashMap<String, String>> {
    let futures = requests.into_iter().map(|req| {
        let client = base_client.clone();
        async move {
            match tokio::time::timeout(total_duration, execute_single_request(req, client)).await {
                Ok(result) => result,
                Err(_) => {
                    let mut timeout_result = HashMap::new();
                    timeout_result.insert("http_status".to_string(), "0".to_string());
                    timeout_result
                }
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

    for req in requests {
        match tokio::time::timeout(total_duration, execute_single_request(req, base_client.clone())).await {
            Ok(result) => results.push(result),
            Err(_) => {
                let mut timeout_result = HashMap::new();
                timeout_result.insert("http_status".to_string(), "0".to_string());
                results.push(timeout_result);
            }
        }
    }

    results
}
