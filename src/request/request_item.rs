use pyo3::prelude::*;
use pyo3::types::PyDict;
use crate::network::{HttpVersion, ProxyConfig, SslVerify};

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
    #[pyo3(get, set)]
    pub http_version: Option<HttpVersion>,
    #[pyo3(get, set)]
    pub ssl_verify: Option<bool>,
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
        proxy: Option<ProxyConfig>,
        http_version: Option<HttpVersion>,
        ssl_verify: Option<bool>,
    ) -> Self {
        Self { url, method, params, timeout, tag, headers, proxy, http_version, ssl_verify }
    }
}
