use pyo3::prelude::*;
use pyo3::types::PyTuple;
use std::collections::{HashMap, HashSet};

fn object_id(bound: &Bound<'_, PyAny>) -> usize {
    bound.as_ptr() as usize
}

fn version_of(bound: &Bound<'_, PyAny>) -> PyResult<u64> {
    bound.getattr("_version")?.extract()
}

#[pyclass(module = "signified._rust_core")]
struct DependencyState {
    deps: Vec<Py<PyAny>>,
    dep_versions: HashMap<usize, u64>,
    next_deps: Option<Vec<Py<PyAny>>>,
    next_seen: HashSet<usize>,
}

#[pymethods]
impl DependencyState {
    #[new]
    fn new() -> Self {
        Self {
            deps: Vec::new(),
            dep_versions: HashMap::new(),
            next_deps: None,
            next_seen: HashSet::new(),
        }
    }

    fn start_refresh(&mut self) {
        self.next_deps = Some(Vec::new());
        self.next_seen.clear();
    }

    fn register_dependency(&mut self, py: Python<'_>, dependency: Py<PyAny>) {
        let dep_id = object_id(dependency.bind(py));
        if let Some(next_deps) = self.next_deps.as_mut() {
            if self.next_seen.insert(dep_id) {
                next_deps.push(dependency);
            }
        }
    }

    fn rollback_refresh(&mut self) {
        self.next_deps = None;
        self.next_seen.clear();
    }

    fn commit_refresh(&mut self, py: Python<'_>, subscriber: Py<PyAny>) -> PyResult<()> {
        let next_deps = self.next_deps.take().unwrap_or_default();
        self.next_seen.clear();

        let mut current_ids = HashSet::with_capacity(self.deps.len());
        for dep in &self.deps {
            current_ids.insert(object_id(dep.bind(py)));
        }

        let mut next_ids = HashSet::with_capacity(next_deps.len());
        for dep in &next_deps {
            next_ids.insert(object_id(dep.bind(py)));
        }

        let subscriber_obj = subscriber.bind(py);

        for dep in &self.deps {
            let dep_ref = dep.bind(py);
            if !next_ids.contains(&object_id(dep_ref)) {
                dep_ref.call_method1("unsubscribe", (subscriber_obj.clone(),))?;
            }
        }

        for dep in &next_deps {
            let dep_ref = dep.bind(py);
            if !current_ids.contains(&object_id(dep_ref)) {
                dep_ref.call_method1("subscribe", (subscriber_obj.clone(),))?;
            }
        }

        let mut dep_versions = HashMap::with_capacity(next_deps.len());
        for dep in &next_deps {
            let dep_ref = dep.bind(py);
            dep_versions.insert(object_id(dep_ref), version_of(dep_ref)?);
        }

        self.deps = next_deps;
        self.dep_versions = dep_versions;
        Ok(())
    }

    fn dependencies_changed(&self, py: Python<'_>) -> PyResult<bool> {
        for dep in &self.deps {
            let dep_ref = dep.bind(py);
            if let Ok(impl_attr) = dep_ref.getattr("_impl") {
                impl_attr.call_method0("ensure_uptodate")?;
            }

            let dep_id = object_id(dep_ref);
            let previous_version = self.dep_versions.get(&dep_id).copied().unwrap_or(u64::MAX);
            if previous_version != version_of(dep_ref)? {
                return Ok(true);
            }
        }
        Ok(false)
    }

    fn clear(&mut self) {
        self.deps.clear();
        self.dep_versions.clear();
        self.next_deps = None;
        self.next_seen.clear();
    }

    #[getter]
    fn deps<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyTuple>> {
        Ok(PyTuple::new_bound(py, self.deps.iter().map(|dep| dep.clone_ref(py))))
    }
}

#[pymodule]
#[pyo3(name = "_rust_core")]
fn signified_rust_core(_py: Python<'_>, module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<DependencyState>()?;
    Ok(())
}
