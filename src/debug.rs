use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::sync::RwLock;
use once_cell::sync::Lazy;
use pyo3::pyfunction;
use reqwest::StatusCode;
use serde_json::Value;

#[derive(Clone)]
enum DebugTarget {
    Console,
    File(String),
}

#[derive(Clone)]
struct DebugConfig {
    enabled: bool,
    target: DebugTarget,
}

static DEBUG_CONFIG: Lazy<RwLock<DebugConfig>> = Lazy::new(|| {
    RwLock::new(DebugConfig { enabled: false, target: DebugTarget::Console })
});

#[pyfunction]
pub fn set_debug(enabled: bool, target: Option<String>) {
    let mut cfg = DEBUG_CONFIG.write().unwrap();
    cfg.enabled = enabled;
    cfg.target = match target {
        Some(t) if t.to_lowercase() == "console" || t.is_empty() => DebugTarget::Console,
        Some(t) => {
            let path = Path::new(&t);
            if path.is_dir() { DebugTarget::File(path.join("debug.log").to_string_lossy().to_string()) }
            else { DebugTarget::File(t) }
        },
        None => DebugTarget::Console,
    };
}

pub fn debug_log(
    method: &str,
    tag: &str,
    url: &str,
    status: StatusCode,
    headers: &serde_json::Map<String, Value>,
    response: &Value,
    proxy: Option<&str>,
    proxy_auth: Option<&str>,
) {
    if !DEBUG_CONFIG.read().unwrap().enabled { return; }

    let mut msg = format!("\n==== [{}] ====\nMethod: {}\nURL: {}\nStatus: {}\n", tag, method, url, status);
    msg.push_str(&format!("Headers: {:?}\nResponse: {}\n", headers, response));
    if let Some(p) = proxy { msg.push_str(&format!("Proxy: {}\n", p)); }
    if let Some(auth) = proxy_auth { msg.push_str(&format!("Proxy Auth: {}\n", auth)); }

    match &DEBUG_CONFIG.read().unwrap().target {
        DebugTarget::Console => println!("{}", msg),
        DebugTarget::File(path) => { let _ = OpenOptions::new().create(true).append(true).open(path).map(|mut f| writeln!(f, "{}", msg)); }
    }
}
