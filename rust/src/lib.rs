use pyo3::prelude::*;

#[pymodule(gil_used = true)]
fn _core(_m: &Bound<'_, PyModule>) -> PyResult<()> {
    Ok(())
}
