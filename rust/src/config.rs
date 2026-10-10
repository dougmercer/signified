//! Opt-in instrumentation: plugin hooks and migration warnings.

use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyString};

use crate::graph::rt;

/// Engine settings, exposed to Python as `signified._core.config`.
///
/// `hooks` is the plugin manager's `hook` object (with `read`, `created`,
/// `updated` and `named` callables), or `None` to turn hooks off.
/// `migration_warnings` mirrors `signified.migration.warnings_enabled()`.
#[pyclass(frozen, module = "signified._core", name = "Config")]
pub struct Config;

#[pymethods]
impl Config {
    #[getter]
    fn hooks(&self, py: Python<'_>) -> Option<Py<PyAny>> {
        rt().hooks
            .borrow()
            .as_ref()
            .map(|hooks| hooks.clone_ref(py))
    }

    #[setter]
    fn set_hooks(&self, py: Python<'_>, hooks: Py<PyAny>) {
        let hooks = if hooks.is_none(py) { None } else { Some(hooks) };
        let rt = rt();
        rt.hooks_on.set(hooks.is_some());
        let old = rt.hooks.replace(hooks);
        drop(old);
    }

    #[getter]
    fn migration_warnings(&self) -> bool {
        rt().migration_warnings.get()
    }

    #[setter]
    fn set_migration_warnings(&self, enabled: bool) {
        rt().migration_warnings.set(enabled);
    }
}

/// Call hook `name` with `value=value`, if hooks are on.
pub(crate) fn hook(
    py: Python<'_>,
    name: &Bound<'_, PyString>,
    value: &Bound<'_, PyAny>,
) -> PyResult<()> {
    let rt = rt();
    if !rt.hooks_on.get() {
        return Ok(());
    }
    let hooks = rt.hooks.borrow().as_ref().map(|hooks| hooks.clone_ref(py));
    let Some(hooks) = hooks else {
        return Ok(());
    };
    let kwargs = PyDict::new(py);
    kwargs.set_item(intern!(py, "value"), value)?;
    hooks.bind(py).getattr(name)?.call((), Some(&kwargs))?;
    Ok(())
}

/// Warn when a signal of a class that opts in receives a reactive value or a
/// container holding one.
pub(crate) fn warn_signal_value(
    py: Python<'_>,
    owner: &Bound<'_, PyAny>,
    value: &Bound<'_, PyAny>,
) -> PyResult<()> {
    if !rt().migration_warnings.get() {
        return Ok(());
    }
    let opted_in = match owner.get_type().getattr(intern!(py, "_WARN_ON_VALUE")) {
        Ok(flag) => flag.is_truthy()?,
        Err(_) => true,
    };
    if opted_in {
        migration(py)?
            .getattr(intern!(py, "_warn_signal_value"))?
            .call1((value,))?;
    }
    Ok(())
}

/// Warn when a computation returns a reactive value or a container holding one.
pub(crate) fn warn_computed_result(
    py: Python<'_>,
    owner: &Bound<'_, PyAny>,
    value: &Bound<'_, PyAny>,
) -> PyResult<()> {
    if !rt().migration_warnings.get() {
        return Ok(());
    }
    migration(py)?
        .getattr(intern!(py, "_warn_reactive_computed_result"))?
        .call1((owner, value))?;
    Ok(())
}

fn migration(py: Python<'_>) -> PyResult<Bound<'_, PyModule>> {
    py.import(intern!(py, "signified.migration"))
}
