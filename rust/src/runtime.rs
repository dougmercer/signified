//! State shared by the whole engine, and the version clock.

use std::cell::Cell;
use std::sync::OnceLock;

use crate::hooks::Hooks;
use crate::node::Node;
use crate::scheduler::Queue;
use crate::tracking::Frames;

/// The engine's global state. The tracking frames, the queue and the hooks
/// each belong to one module, which alone can see inside them.
#[derive(Default)]
pub(crate) struct Runtime {
    clock: Cell<u64>,
    /// Nesting of notification walks; effects run when it returns to zero.
    pub(crate) wave_depth: Cell<u32>,
    pub(crate) frames: Frames,
    pub(crate) queue: Queue,
    pub(crate) hooks: Hooks,
}

// SAFETY: as for `Shared`; one runtime is shared by all threads, like a
// module's globals, and the GIL serializes access.
unsafe impl Send for Runtime {}
unsafe impl Sync for Runtime {}

pub(crate) fn rt() -> &'static Runtime {
    static RT: OnceLock<Runtime> = OnceLock::new();
    RT.get_or_init(Runtime::default)
}

pub(crate) fn clock() -> u64 {
    rt().clock.get()
}

/// Advance the global version clock.
pub(crate) fn bump_clock() -> u64 {
    let rt = rt();
    let version = rt.clock.get() + 1;
    rt.clock.set(version);
    version
}

/// Advance the clock and stamp `node` with the new version. Versions are
/// unique across nodes and never reused.
pub(crate) fn bump_version(node: &Node) -> u64 {
    let version = bump_clock();
    node.version.set(version);
    version
}
