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
    #[pyo3(get, set)]
    pub username: Option<String>,
    #[pyo3(get, set)]
    pub password: Option<String>,
    #[pyo3(get, set)]
    pub trust_env: Option<bool>,
}

#[pymethods]
impl ProxyConfig {
    #[new]
    #[pyo3(signature = (http=None, https=None, all=None, no_proxy=None, username=None, password=None, trust_env=None))]
    fn new(
        http: Option<String>,
        https: Option<String>,
        all: Option<String>,
        no_proxy: Option<Vec<String>>,
        username: Option<String>,
        password: Option<String>,
        trust_env: Option<bool>, // 新增参数，默认为None
    ) -> Self {
        Self {
            http,
            https,
            all,
            no_proxy,
            username,
            password,
            trust_env,
        }
    }

    #[staticmethod]
    #[pyo3(signature = (proxy_url, username=None, password=None, trust_env=None))]
    fn from_url(
        proxy_url: String,
        username: Option<String>,
        password: Option<String>,
        trust_env: Option<bool> // 新增参数
    ) -> Self {
        Self {
            http: None,
            https: None,
            all: Some(proxy_url),
            no_proxy: None,
            username,
            password,
            trust_env,
        }
    }

    #[staticmethod]
    #[pyo3(signature = (http=None, https=None, username=None, password=None, trust_env=None))]
    fn from_dict(
        http: Option<String>,
        https: Option<String>,
        username: Option<String>,
        password: Option<String>,
        trust_env: Option<bool> // 新增参数
    ) -> Self {
        Self {
            http,
            https,
            all: None,
            no_proxy: None,
            username,
            password,
            trust_env,
        }
    }
}