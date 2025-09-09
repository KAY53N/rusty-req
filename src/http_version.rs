// src/http_version.rs
use pyo3::{pyclass, pymethods, PyResult};
use pyo3::exceptions::PyValueError;
use reqwest::ClientBuilder;

#[pyclass]
#[derive(Clone, PartialEq, Debug)]
pub enum HttpVersion {
    #[pyo3(name = "AUTO")]
    Auto,           // 自动协商（默认）
    #[pyo3(name = "HTTP1_ONLY")]
    Http1Only,      // 仅使用 HTTP/1.1
    #[pyo3(name = "HTTP2")]
    Http2,          // 优先尝试 HTTP/2，可回退到 HTTP/1.1
    #[pyo3(name = "HTTP2_PRIOR_KNOWLEDGE")]
    Http2PriorKnowledge, // 强制 HTTP/2（无回落）
}

#[pymethods]
impl HttpVersion {
    #[new]
    fn new() -> Self {
        HttpVersion::Auto
    }

    // 类属性常量
    #[classattr]
    const AUTO: HttpVersion = HttpVersion::Auto;

    #[classattr]
    const HTTP1_ONLY: HttpVersion = HttpVersion::Http1Only;

    #[classattr]
    const HTTP2: HttpVersion = HttpVersion::Http2;

    #[classattr]
    const HTTP2_PRIOR_KNOWLEDGE: HttpVersion = HttpVersion::Http2PriorKnowledge;

    // 字符串表示
    fn __str__(&self) -> &'static str {
        match self {
            HttpVersion::Auto => "AUTO",
            HttpVersion::Http1Only => "HTTP1_ONLY",
            HttpVersion::Http2 => "HTTP2",
            HttpVersion::Http2PriorKnowledge => "HTTP2_PRIOR_KNOWLEDGE",
        }
    }

    fn __repr__(&self) -> String {
        format!("HttpVersion.{}", self.__str__())
    }

    // 从字符串创建
    #[staticmethod]
    fn from_str(s: &str) -> PyResult<Self> {
        match s.to_uppercase().as_str() {
            "AUTO" | "" => Ok(HttpVersion::Auto),
            "HTTP1" | "HTTP1.1" | "HTTP1_ONLY" => Ok(HttpVersion::Http1Only),
            "HTTP2" => Ok(HttpVersion::Http2),
            "HTTP2_PRIOR_KNOWLEDGE" | "FORCE_HTTP2" | "HTTP2_ONLY" => Ok(HttpVersion::Http2PriorKnowledge),
            _ => Err(PyValueError::new_err(
                format!("Invalid HTTP version: '{}'. Valid values: AUTO, HTTP1_ONLY, HTTP2, HTTP2_PRIOR_KNOWLEDGE", s)
            )),
        }
    }

    // 获取描述信息
    fn description(&self) -> &'static str {
        match self {
            HttpVersion::Auto => "Automatically negotiate the best HTTP version",
            HttpVersion::Http1Only => "Use only HTTP/1.1 (no HTTP/2)",
            HttpVersion::Http2 => "Prefer HTTP/2, fallback to HTTP/1.1 if needed",
            HttpVersion::Http2PriorKnowledge => "Force HTTP/2 without fallback (server must support HTTP/2)",
        }
    }

    // 检查是否支持 HTTP/2
    fn supports_http2(&self) -> bool {
        match self {
            HttpVersion::Auto | HttpVersion::Http2 | HttpVersion::Http2PriorKnowledge => true,
            HttpVersion::Http1Only => false,
        }
    }

    // 检查是否强制 HTTP/2
    fn is_http2_forced(&self) -> bool {
        matches!(self, HttpVersion::Http2PriorKnowledge)
    }
}

impl HttpVersion {
    // 转换为 reqwest 配置（这个方法不需要 #[pymethods] 标记）
    pub(crate) fn apply_to_builder(&self, builder: ClientBuilder) -> ClientBuilder {
        match self {
            HttpVersion::Auto => builder,
            HttpVersion::Http1Only => builder.http1_only(),
            HttpVersion::Http2 => builder,
            HttpVersion::Http2PriorKnowledge => builder.http2_prior_knowledge(),
        }
    }
}