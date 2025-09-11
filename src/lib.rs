#![allow(non_local_definitions)]

mod network;
mod request;
mod debug;
mod utils;

use pyo3::prelude::*;
use once_cell::sync::Lazy;
use tokio::sync::Mutex;
use reqwest::Client;

pub use network::{HttpVersion, ProxyConfig};
pub use request::{RequestItem, fetch_single, fetch_requests, set_global_proxy};
pub use crate::debug::set_debug;
pub use request::concurrency::ConcurrencyMode;

// 全局 Client 和 Proxy
const DEFAULT_USER_AGENT: &str = "Rust/1.88.0 (6b00bc388) reqwest/0.11.27";

pub static GLOBAL_CLIENT: Lazy<Mutex<Client>> = Lazy::new(|| {
    Mutex::new(
        Client::builder()
            .timeout(std::time::Duration::from_secs(30))
            .gzip(true)
            .brotli(true)
            .deflate(true)
            .user_agent(DEFAULT_USER_AGENT)
            .build()
            .expect("Failed to create HTTP client"),
    )
});

pub static GLOBAL_PROXY: Lazy<Mutex<Option<ProxyConfig>>> = Lazy::new(|| Mutex::new(None));

#[pymodule]
fn rusty_req(_py: Python, m: &PyModule) -> PyResult<()> {
    // 暴露类
    m.add_class::<ProxyConfig>()?;
    m.add_class::<ConcurrencyMode>()?;
    m.add_class::<RequestItem>()?;
    m.add_class::<HttpVersion>()?;

    // 暴露函数
    use pyo3::wrap_pyfunction;
    m.add_function(wrap_pyfunction!(set_debug, m)?)?;
    m.add_function(wrap_pyfunction!(fetch_single, m)?)?;
    m.add_function(wrap_pyfunction!(fetch_requests, m)?)?;
    m.add_function(wrap_pyfunction!(set_global_proxy, m)?)?;

    Ok(())
}
