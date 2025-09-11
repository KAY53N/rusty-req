// src/network/mod.rs
pub mod http_version;
pub mod proxy_config;

// 重新导出，方便外部使用
pub use http_version::HttpVersion;
pub use proxy_config::ProxyConfig;