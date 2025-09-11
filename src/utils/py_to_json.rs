use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use serde_json::{Value};

pub fn py_to_json(py: Python, obj: &PyAny) -> PyResult<Value> {
    if let Ok(b) = obj.extract::<bool>() { return Ok(Value::Bool(b)); }
    if let Ok(s) = obj.extract::<String>() { return Ok(Value::String(s)); }
    if let Ok(i) = obj.extract::<i64>() { return Ok(Value::Number(i.into())); }
    if let Ok(f) = obj.extract::<f64>() { return Ok(Value::Number(serde_json::Number::from_f64(f).unwrap_or(0.into()))); }
    if let Ok(list) = obj.downcast::<PyList>() {
        let mut vec = Vec::new();
        for i in list.iter() { vec.push(py_to_json(py, i)?); }
        return Ok(Value::Array(vec));
    }
    if let Ok(dict) = obj.downcast::<PyDict>() {
        let mut map = serde_json::Map::new();
        for (k,v) in dict.iter() { map.insert(k.to_string(), py_to_json(py, v)?); }
        return Ok(Value::Object(map));
    }
    Ok(Value::String(obj.to_string()))
}
