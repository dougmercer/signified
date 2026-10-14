//! Plugin hooks: the engine calls a plugin's `read`, `created` and `updated`
//! hooks, which are set through `signified._core.config`.

use std::cell::{Cell, RefCell};
use std::rc::Rc;

use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyString};

use crate::engine::node::Node;
use crate::engine::sampling;

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

/// The hooks a plugin implements, indexed by `Hook`.
type Callers = [Option<Py<PyAny>>; Hook::ALL.len()];

/// The hooks the engine calls. One set serves every thread.
struct Hooks {
    /// The plugin manager's `hook` object, when hooks are on.
    manager_hook: RefCell<Option<Py<PyAny>>>,
    callers: RefCell<Callers>,
    /// One bit per hook in `callers`, and `SAMPLING`.
    on: Cell<u8>,
    /// Substitutions active on all threads (see `engine::sampling`).
    substitutions: Cell<u32>,
}

/// Set in `on` while any thread evaluates a sample, so a read checks for a
/// substitution with the same load that checks for a read hook.
const SAMPLING: u8 = 1 << 7;

// SAFETY: only touched while attached to an interpreter that holds the GIL,
// which serializes access; see `Shared` in `shared`.
unsafe impl Sync for Hooks {}

static HOOKS: Hooks = Hooks {
    manager_hook: RefCell::new(None),
    callers: RefCell::new([None, None, None]),
    on: Cell::new(0),
    substitutions: Cell::new(0),
};

fn hooks() -> &'static Hooks {
    &HOOKS
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
        hooks()
            .manager_hook
            .borrow()
            .as_ref()
            .map(|hooks| hooks.clone_ref(py))
    }

    #[setter]
    fn set_hooks(&self, py: Python<'_>, hooks: Py<PyAny>) -> PyResult<()> {
        let mut callers = Callers::default();
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
        let manager_hook = if hooks.is_none(py) { None } else { Some(hooks) };
        let state = self::hooks();
        state.on.set(on | (state.on.get() & SAMPLING));
        let old = (
            state.manager_hook.replace(manager_hook),
            state.callers.replace(callers),
        );
        drop(old);
        Ok(())
    }
}

/// A substitution became active on some thread.
pub(crate) fn begin_sampling() {
    let state = hooks();
    state.substitutions.set(state.substitutions.get() + 1);
    state.on.set(state.on.get() | SAMPLING);
}

/// A substitution ended.
pub(crate) fn end_sampling() {
    let state = hooks();
    let active = state.substitutions.get() - 1;
    state.substitutions.set(active);
    if active == 0 {
        state.on.set(state.on.get() & !SAMPLING);
    }
}

/// Whether a substitution is active on any thread.
#[inline(always)]
pub(crate) fn sampling_active() -> bool {
    hooks().on.get() & SAMPLING != 0
}

/// Whether a read must take `special_read`: a read hook is on, or a sample is
/// being evaluated.
#[inline(always)]
pub(crate) fn read_is_special() -> bool {
    hooks().on.get() & (Hook::Read.bit() | SAMPLING) != 0
}

/// A read's slow path: call the read hook, then let an active substitution
/// answer the read. `None` means read the live graph as usual.
#[cold]
#[inline(never)]
pub(crate) fn special_read<'py>(
    py: Python<'py>,
    node: &Rc<Node>,
    handle: &Bound<'py, PyAny>,
) -> PyResult<Option<Bound<'py, PyAny>>> {
    call(py, Hook::Read, handle)?;
    if sampling_active() {
        return sampling::read(py, node);
    }
    Ok(None)
}

/// Whether a plugin implements `hook`.
pub(crate) fn is_on(hook: Hook) -> bool {
    hooks().on.get() & hook.bit() != 0
}

/// Call `hook` with `value=value`, if a plugin implements it.
pub(crate) fn call(py: Python<'_>, hook: Hook, value: &Bound<'_, PyAny>) -> PyResult<()> {
    let hooks = hooks();
    if hooks.on.get() & hook.bit() == 0 {
        return Ok(());
    }
    let caller = hooks.callers.borrow()[hook as usize]
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
