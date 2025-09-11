use pyo3::{pyfunction, PyAny, PyResult, Python};
use crate::{ProxyConfig, GLOBAL_PROXY};

#[pyfunction]
pub fn set_global_proxy<'py>(py: Python<'py>, proxy: ProxyConfig) -> PyResult<&'py PyAny> {
    pyo3_asyncio::tokio::future_into_py(py, async move {
        let mut global = GLOBAL_PROXY.lock().await;
        *global = Some(proxy);
        Ok(())
    })
}
