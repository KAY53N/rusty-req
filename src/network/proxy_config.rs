use pyo3::{pyclass, pymethods};

#[pyclass]
#[derive(Clone)]
pub struct ProxyConfig {
    #[pyo3(get, set)]
    pub http: Option<String>,
    #[pyo3(get, set)]
    pub https: Option<String>,
    #[pyo3(get, set)]
    pub all: Option<String>,
    #[pyo3(get, set)]
    pub no_proxy: Option<Vec<String>>,
    // 新增用户名密码字段
    #[pyo3(get, set)]
    pub username: Option<String>,
    #[pyo3(get, set)]
    pub password: Option<String>,
}

#[pymethods]
impl ProxyConfig {
    #[new]
    fn new(
        http: Option<String>,
        https: Option<String>,
        all: Option<String>,
        no_proxy: Option<Vec<String>>,
        username: Option<String>,  // 新增参数
        password: Option<String>,  // 新增参数
    ) -> Self {
        Self {
            http,
            https,
            all,
            no_proxy,
            username,
            password
        }
    }

    #[staticmethod]
    fn from_url(proxy_url: String, username: Option<String>, password: Option<String>) -> Self {
        Self {
            http: None,
            https: None,
            all: Some(proxy_url),
            no_proxy: None,
            username,
            password
        }
    }

    #[staticmethod]
    fn from_dict(
        http: Option<String>,
        https: Option<String>,
        username: Option<String>,
        password: Option<String>
    ) -> Self {
        Self {
            http,
            https,
            all: None,
            no_proxy: None,
            username,
            password
        }
    }
}