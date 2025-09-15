// src/network/mod.rs
pub mod http_version;
pub mod proxy_config;
pub mod ssl_verify;  // 新增

// 重新导出，方便外部使用
pub use http_version::HttpVersion;
pub use proxy_config::ProxyConfig;
pub use ssl_verify::SslVerify;  // 新增导出