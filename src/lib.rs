#![allow(non_local_definitions)]

mod network;
mod request;
mod debug;
mod utils;

use std::process::Command;
use pyo3::prelude::*;
use once_cell::sync::Lazy;
use tokio::sync::Mutex;
use reqwest::Client;
pub use network::{HttpVersion, ProxyConfig};
pub use request::{RequestItem, fetch_single, fetch_requests, set_global_proxy};
pub use crate::debug::set_debug;
pub use request::concurrency::ConcurrencyMode;
use crate::network::SslVerify;

pub static DEFAULT_USER_AGENT: Lazy<String> = Lazy::new(|| {
    let rust_version = Command::new("rustc")
        .arg("--version")
        .output()
        .ok()
        .and_then(|output| String::from_utf8(output.stdout).ok())
        .map(|v| v.trim().to_string())
        .unwrap_or_else(|| "unknown".to_string());

    format!("Rust/{} rusty-req/{}", rust_version, env!("CARGO_PKG_VERSION"))
});

pub static GLOBAL_CLIENT: Lazy<Mutex<Client>> = Lazy::new(|| {
    Mutex::new(
        Client::builder()
            .timeout(std::time::Duration::from_secs(30))
            .gzip(true)
            .brotli(true)
            .deflate(true)
            .user_agent(&*DEFAULT_USER_AGENT)  // 复用静态变量
            .build()
            .expect("Failed to create HTTP client"),
    )
});

// 移除单独的 DEFAULT_USER_AGENT 定义
pub static GLOBAL_PROXY: Lazy<Mutex<Option<ProxyConfig>>> = Lazy::new(|| Mutex::new(None));

#[pymodule]
fn rusty_req(_py: Python, m: &PyModule) -> PyResult<()> {
    // 添加版本信息
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;

    // 暴露类
    m.add_class::<ProxyConfig>()?;
    m.add_class::<ConcurrencyMode>()?;
    m.add_class::<RequestItem>()?;
    m.add_class::<HttpVersion>()?;
    m.add_class::<SslVerify>()?;

    // 暴露函数
    use pyo3::wrap_pyfunction;
    m.add_function(wrap_pyfunction!(set_debug, m)?)?;
    m.add_function(wrap_pyfunction!(fetch_single, m)?)?;
    m.add_function(wrap_pyfunction!(fetch_requests, m)?)?;
    m.add_function(wrap_pyfunction!(set_global_proxy, m)?)?;

    Ok(())
}
