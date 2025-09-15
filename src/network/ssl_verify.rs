use pyo3::{pyclass, pymethods};

#[pyclass]
#[derive(Clone, Debug)]
pub struct SslVerify(bool);

#[pymethods]
impl SslVerify {
    #[new]
    fn new(verify: bool) -> Self {
        SslVerify(verify)
    }

    // 添加一个方法获取内部 bool 值
    pub fn get(&self) -> bool {
        self.0
    }
}