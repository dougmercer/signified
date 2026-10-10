//! Plugin hooks.

use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyString};

use crate::graph::rt;

/// A plugin hook the engine calls.
#[derive(Clone, Copy)]
pub(crate) enum Hook {
    Read,
    Created,
    Updated,
}

impl Hook {
    const ALL: [Hook; 3] = [Hook::Read, Hook::Created, Hook::Updated];

    fn name<'py>(self, py: Python<'py>) -> &'py Bound<'py, PyString> {
        match self {
            Hook::Read => intern!(py, "read"),
            Hook::Created => intern!(py, "created"),
            Hook::Updated => intern!(py, "updated"),
        }
    }

    fn bit(self) -> u8 {
        1 << self as u8
    }
}

/// Engine settings, exposed to Python as `signified._core.config`.
///
/// `hooks` is the plugin manager's `hook` object, or `None` to turn hooks
/// off. When it is set, the engine records which of its `read`, `created` and
/// `updated` callables are present and truthy, and calls only those; set it
/// again after they change. (`named` is called from Python.)
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
    fn set_hooks(&self, py: Python<'_>, hooks: Py<PyAny>) -> PyResult<()> {
        let mut callers: [Option<Py<PyAny>>; 3] = [None, None, None];
        let mut on = 0;
        if !hooks.is_none(py) {
            for hook in Hook::ALL {
                if let Some(caller) = hooks.bind(py).getattr_opt(hook.name(py))? {
                    if caller.is_truthy()? {
                        on |= hook.bit();
                        callers[hook as usize] = Some(caller.unbind());
                    }
                }
            }
        }
        let hooks = if hooks.is_none(py) { None } else { Some(hooks) };
        let rt = rt();
        rt.hooks_on.set(on);
        let old = (rt.hooks.replace(hooks), rt.hook_callers.replace(callers));
        drop(old);
        Ok(())
    }
}

/// Call `hook` with `value=value`, if a plugin implements it.
pub(crate) fn hook(py: Python<'_>, hook: Hook, value: &Bound<'_, PyAny>) -> PyResult<()> {
    let rt = rt();
    if rt.hooks_on.get() & hook.bit() == 0 {
        return Ok(());
    }
    let caller = rt.hook_callers.borrow()[hook as usize]
        .as_ref()
        .map(|caller| caller.clone_ref(py));
    let Some(caller) = caller else {
        return Ok(());
    };
    let kwargs = PyDict::new(py);
    kwargs.set_item(intern!(py, "value"), value)?;
    caller.bind(py).call((), Some(&kwargs))?;
    Ok(())
}
