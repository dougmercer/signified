# Changelog

This page summarizes notable changes across releases.

## Unreleased

- `Watcher` reports which of many reactive values changed since you last
  asked: `watch(value, key)`, then `changed()` once per step of your own (a
  frame, a tick) gives the keys whose values changed. A change only marks the
  watch, and `changed()` reads only the marked values, so values that didn't
  change cost nothing; a calculation that recalculated to the same result is
  not reported. See [Ask which values changed](usage.md#watchers).
- `sample(value, signal, at)` taken at the signal's current value shares the
  live result and keeps it once `signal` moves on, instead of calculating it
  again for `at`.

## 0.7.2

### `sample()`

`sample(value, signal, at)` returns a [Computed][signified.Computed] holding
`value` as if `signal` held `at`. Nothing else changes: not the signal, and not
any cached value.

```py
frame = Signal(0)
position = computed(lambda f: f * 10)(frame)

held = sample(position, frame, 3)  # position at frame 3, on every frame
until = sample(position, frame, computed(lambda f: min(f, 3))(frame))  # live, then held from frame 3
```

- The result recalculates when `at` changes, or when something `value` reads
  other than `signal` changes. Changing only `signal` leaves it cached.
- `at` may be reactive. It is read with the signal's real value, then
  substituted.
- It works inside computeds, through branches, `untracked()`, `Binding` and
  native nodes, and samples can be nested.
- Values are calculated as on a first read, so a computed's custom `equal` has
  no earlier value to keep. Where `Signal.at()` would keep a cached value that
  `equal` accepts, `sample()` gives the new one.
- Reads cost nothing extra in a program that never calls `sample()`.

Use `Signal.at()` to run code as if a signal held another value, and
`sample()` to keep a value from another value of a signal.

### Breaking changes

- **Breaking:** A `Computed` can no longer change a signal while it is being
  evaluated. Doing so raises `RuntimeError`, which is cached like any other
  error from the function. Previously such a change could leave dependents
  stuck on an old value for good; for example, `with frame.at(f):` inside a
  computed froze everything downstream. The rule covers:

    - assigning `.value` or a `tracked_fields` attribute;
    - `Signal.at()` with a value other than the current one;
    - `update()`, `invalidate()`, item assignment, item deletion and attribute
      assignment on a `Signal`;
    - `invalidate()` on a `Computed`.

    It applies inside `untracked()` too, and in a custom `equal` or a plugin's
    `updated` hook while a computed is refreshing. Assigning the value a signal
    already holds is still allowed, as are writes from effects and from code
    outside computeds. Use `sample()` in place of `Signal.at()` inside a
    computed.

## 0.7.1

### Fixes

- A plugin's `updated` hook that raises no longer leaves dependents stale.
- `copy.copy()` of a `tracked_fields` instance that keeps its fields in the
  instance dict now holds the values it was copied with.
- A `Computed` with `equal=` no longer calls `equal` for a new result that the
  built-in rules already count as unchanged, such as a newly created `int`
  equal to the previous one. `Signal` already worked this way, as described
  in [What counts as a change](compute-contract.md#what-counts-as-a-change).

### Runtime improvements

- `tracked_fields` attributes are now read and written by a compiled
  descriptor. Reading a field outside a calculation is about three times
  faster, and assigning one about twice as fast.
- Refreshing a computed value no longer copies its function and arguments
  first, which saves an allocation and reference-count updates on every
  refresh.

## 0.7.0

### Breaking changes

- **Breaking:** Signified's reactive engine is now a compiled extension written
  in Rust (`signified._core`). `Signal`, `Computed`, `Binding` and `Effect` keep
  their API, and most graphs update several times faster. Behavior changes:

    - A signal written twice while a change is propagating now notifies both
      times. Previously the second write could leave a dependent computed stale.
    - Subclasses can no longer override `update()` or `value`; defining either
      raises `TypeError`. Derive a `Computed` (for example
      with `signal.rx.map(fn)`) instead of overriding `value`.
    - `copy.copy()` and `copy.deepcopy()` of a `Signal`, `Computed` or `Binding`
      raise `TypeError`. Deep-copying a `Computed` previously produced an object
      that never updated. Instances using `tracked_fields` still copy and pickle.
    - Reading or writing a `Signal` whose `__init__` was never called raises
      `RuntimeError`.
- **Breaking:** `subscribe()`, `unsubscribe()`, and `notify()` on `Signal`,
  `Computed`, and `Binding` are now private. Use an `Effect` to react to
  changes.
- **Breaking:** Removed `signified.plugins.pm`; use `plugin_manager`.
- **Breaking:** Removed the migration warnings added in 0.6:
  `signified.migration` and `SIGNIFIED_MIGRATION_WARNINGS`. To check code
  written for 0.5, run the warnings on 0.6 before upgrading; see
  [Migrating to 0.6](migration.md#optional-migration-diagnostics).

### Runtime improvements

- Each thread now tracks reads, batches, and effects on its own. Previously two
  threads using Signified at once, even with unrelated graphs, could raise
  `RuntimeError: tracking frames are unbalanced`, record a read on one thread
  as a dependency of a computation on another, or hold back each other's
  effects. Separate graphs can now run on separate threads, and a graph can be
  handed from one thread to another. Use one graph from one thread at a time:
  reading a `Computed` while another thread is computing it raises
  `RuntimeError`.

### Packaging

- Signified now ships a compiled extension, built with maturin. Wheels cover
  CPython 3.12 and later on Linux (x86_64 and aarch64, glibc and musl), macOS
  (Intel and Apple silicon), Windows x64, and Pyodide 314 (Python 3.14).
  Installing on other platforms builds from source and needs a Rust toolchain.
  Under Pyodide, a value more than 250 refreshes deep raises `RecursionError`,
  because the browser's stack is much smaller than a native one.
- Plugin hooks run whenever a plugin is registered with `plugin_manager`;
  `SIGNIFIED_ENABLE_HOOKS` and `signified.plugins.HOOKS_ENABLED` are removed.
- Plugins no longer use pluggy, and the `plugins` extra is removed.
  `@hookimpl`, `plugin_manager.register`, and `plugin_manager.unregister` work
  as before. `register` now rejects an `@hookimpl` method whose name is not a
  known hook, and no longer takes a `name` argument. pluggy options such as
  `@hookimpl(tryfirst=True)` and hook wrappers are not supported.
- Removed the `ipython` extra. Notebook display works the same without it.

## 0.6.1

### Breaking changes

- **Breaking:** Reactive objects no longer overload `!=`. Comparisons between
  reactive objects use identity and return a plain `bool`, matching `==`.
  Replace `(x != y)` with `x.rx.ne(y)` for reactive value comparisons, alongside
  the existing `x.rx.eq(y)`.

### Runtime improvements

- Added `tracked_fields`, a class decorator that makes reassigning an attribute
  invalidate computations that read it. Reads return the stored value unchanged.
  It works with slotted and dict-based dataclasses, or named attributes of other
  classes.
- `Signal` and `Computed` accept `equal=`, a custom equality such as
  `np.array_equal`. When it reports a new value equal to the previous one, the
  previous object is kept and dependents are not invalidated.
  `x.rx.with_equal(equal)` sets it on an existing value, including values built
  by operators, `computed`, and `rx.map`, and returns that value.
- `Signal` forwards item deletion (`del signal[key]`) to the wrapped `list` or
  `dict` and notifies observers, like `signal[key] = value`.
- `Signal.at()` and `Binding.at()` restore the previous version as well as the
  previous value on exit. Dependents that were not read inside the `with` block
  no longer recompute afterwards.
- `other @ reactive`, `other << reactive`, and `other >> reactive` now produce
  reactive values instead of raising `TypeError`.
- Operators with a NumPy array on the left, such as `array + reactive` or
  `array < reactive`, now return one `Computed` instead of an array of
  `Computed` objects. Passing a reactive value straight to a ufunc, as in
  `np.sin(reactive)`, now raises `TypeError`; use `reactive.rx.map(np.sin)`.

### Type inference

Type checkers infer more precise results for reactive operators and helpers,
and reject operations the wrapped type does not support.

- Operators report the wrapped type's declared result, with the plain or
  reactive value on either side, instead of a union of the operand types.
  Built-in numbers follow Python's promotion rules, so `Signal(1) / 2` is
  `Computed[float]`. Dates and datetimes subtract to `timedelta`, and adding or
  subtracting a `timedelta` keeps the date type.
- `abs`, `round`, `divmod`, `math.floor`, `math.ceil`, `math.trunc`, and unary
  `-`, `+`, and `~` infer the declared result, such as `Computed[int]` for
  `round(x)` and `Computed[Decimal]` for `round(decimal, 2)`.
- Indexing keeps the item type, and slicing a list, tuple, or string with a
  reactive slice keeps the container type. `rx.contains` and `rx.in_` reject
  containers that do not support membership.
- `rx.eq`, `rx.ne`, and `rx.as_bool` keep custom and literal result types, so
  `rx.where` can narrow its result when the condition is known to be true or
  false.
- `as_rx`, and `rx` helpers that return the source, such as `rx.with_equal`,
  keep the exact `Signal`, `Computed`, or `Binding` type.
- Known gap: `divmod(reactive, plain)` loses its type when only the plain
  value's type defines `__rdivmod__`. Wrapping it in `Signal` restores inference.

## 0.6.0

- Added `Binding` for switching the source followed by existing calculations.
- Added `batch()` to group writes before effects run, and `untracked()` to read
  values without adding dependencies.
- **Breaking:** signals now store reactive objects as-is, and computed values
  can return them as-is. `unref` reads one reactive object at a time.
- **Breaking:** decorated functions read direct reactive arguments only. Use
  `deep_unref` inside callbacks to read nested containers, and register custom
  iterable types to keep resolving their contents.
- Change detection now compares exact built-in scalars by value and other
  objects by identity. Computations and effects skip work when their calculated
  inputs are unchanged, including after an equal-valued binding source change.
- Computed values save ordinary exceptions until an input changes or they are
  explicitly invalidated. Failed runs track the inputs they reached and can recover.
- Effects run after affected calculations are marked for refresh. Multiple
  effect failures are reported together as an `ExceptionGroup`.
- **Breaking:** only `Signal` forwards attribute and item writes. Unknown
  attribute names raise `AttributeError`.
- Removed `rx.peek(fn)`; use `rx.tap(fn)`.

See [Migrating to 0.6](migration.md) for required code changes and
[How updates work](compute-contract.md) for the full behavior.

## 0.5.1

Add `is_reactive` to inspect wrappers without reading their values. Improve
union inference for `unref` and `as_rx`; runtime resolution is unchanged.

Add `deep_unref.register(Type)` for custom containers and retain NumPy shape/dtype.
Repeated references are resolved independently; cycles raise `RecursionError`.
Resolved key/member collisions raise `ValueError` instead of silently discarding
entries, and unhashable keys/members raise `TypeError`.
Legacy traversal of unregistered iterables warns that it will be removed in 0.6.0.

Add opt-in migration diagnostics with `migration.enable_warnings()` or
`SIGNIFIED_MIGRATION_WARNINGS=1`, including nested containers and safe cleanup
when warnings are treated as errors. Existing resolution and propagation stay
in place while applications identify affected patterns.

Add `rx.tap(fn)` for the lazy cached callback helper. `rx.peek(fn)` remains a
deprecated alias until its removal in 0.6.0. Repeated cached reads do not rerun
the callback; unread intermediate updates are skipped.

See [Migrating to 0.6](migration.md) for changes you can make on 0.5.1 and
changes that require upgrading the runtime.

## 0.5.0

### Removals

The following deprecated APIs were removed. Their replacements are listed
below.

Functions

* `reactive_method` — use `computed` instead.
* `as_signal` — use `as_rx` instead.

Arguments

* `Computed(fn, dependencies=...)` — use `Computed(fn)` instead.

Public Methods

* `Variable.add_name` — use `Variable.with_name` instead.
* `Variable.as_bool` — use `Variable.rx.as_bool` instead.
* `Variable.contains` — use `Variable.rx.contains` instead.
* `Variable.is_not` — use `Variable.rx.is_not` instead.
* `Variable.eq` — use `Variable.rx.eq` instead.
* `Variable.where` — use `Variable.rx.where` instead.

Plumbing Methods

* `Variable.observe` — use `Variable._observe` instead.
* `Variable.unobserve` — use `Variable._unobserve` instead.

## 0.4.0

### `@effect` decorator

A new `@effect` decorator mirrors `@computed`, making it easy to define reactive side effects as plain functions:

```python
@effect
def log(x):
    print(x)

e = log(some_signal)  # runs immediately, re-runs on change
```

Like `@computed`, arguments are automatically unwrapped, so the function always receives plain Python values. The effect stays active as long as you hold a reference to the returned `Effect`.

### Performance improvements

The internals were substantially reworked for speed:

- Observer subscriptions are now stored as intrusive linked lists, reducing allocation overhead for high-fan-out signals.
- `Computed` nodes reuse existing dependency links across re-evaluations instead of rebuilding them from scratch.
- Invalidation uses a global version counter to short-circuit redundant recomputation in deep graphs.
- Common cases in `computed`, `effect`, and other internal implementation details now have cheaper early-exit paths.

## 0.3.2

### Bug fixes

Fix bug causing `__getattr__` to do infinite loops when the object attempts to be deep copied.

Make `__setattr__` slightly more robust.

## 0.3.1

### Effect rework

`Effect` now auto-tracks its dependencies the same way `Computed` does. The constructor signature has changed: instead of taking a reactive source and a callback, it now takes a single zero-argument callable. Every reactive value read via `.value` or `unref()` inside that callable is automatically registered as a dependency.

```python
# Before (0.3.0)
e = Effect(s, lambda v: print(v))

# After (0.3.1)
e = Effect(lambda: print(s.value))
```

Conditional branches are handled correctly — only the signals actually read during the most recent run are tracked, and the dependency set updates automatically when branches change.

### `unref()` now participates in dependency tracking

Calling `unref()` inside a `Computed` or `Effect` evaluation now registers each unwrapped reactive as a dependency, the same as reading `.value` directly. Previously `unref()` bypassed tracking entirely.

### Invalidation API

Added `invalidate()` to all reactive values. For `Computed`, pass `force=True` to bypass the dependency-version check and guarantee a full re-evaluation on the next read. Use this when the dependency topology changes outside the reactive graph (for example, replacing an object attribute that points to a signal or computed).

### Bug Fixes

- Fixed transient computed dependency retention: dependencies are now held strongly during evaluation, preventing them from being dropped by garbage collection before downstream updates complete.
- Fixed exception rollback in `Computed` and `Effect`: if the user function raises, the previous dependency set and staleness state are preserved so the node retries correctly on the next change.

!!! danger "Breaking Changes"

    - **`Effect` constructor**: the two-argument form `Effect(source, fn)` is gone. Replace with `Effect(lambda: fn(source.value))`.
    - **`NestedValue` removed**: `from signified import NestedValue` will raise `ImportError`. Use `HasValue` or `ReactiveValue`; explicit source chains use `Binding`.
    - **Internal module renames**: the private implementation modules have been reorganised. Any code importing directly from `signified.core`, `signified.types`, or `signified.display` will break. Use the public `signified` namespace instead.

!!! warning "Deprecations"

    - `as_signal(val)` — use `as_rx(val)` instead.

## 0.3.0

### Dependency Tracking

`Computed` now tracks its dependencies automatically at runtime — no need to declare them upfront. Values are only recomputed when actually read, and if a recomputed value turns out to be unchanged, downstream computeds won't needlessly re-run.

### Change Detection

Signified is smarter about deciding when a `Signal`'s value has actually changed:

- Functions are compared by identity rather than equality.
- Arrays are compared element-by-element.
- Assigning `NaN` to a signal that already holds `NaN` is treated as no change.

Mutating a signal's contents (e.g. setting an attribute or index) now also correctly invalidates downstream computeds, and `unref`/`deep_unref` align with how dependencies are tracked at runtime.

### rx namespace

Added `Signal.rx` namespace which includes several methods:

  - map (new) - lazy transform helper for derived values.
  - peek (new) - lazy pass-through side-effect helper (observational effects).
  - effect (new) - eager side-effect subscription with explicit `dispose()`.
  - len (new)
  - is_ (new)
  - is_not
  - in_ (new)
  - contains
  - eq
  - where
  - as_bool

### Bug Fixes

Fixed a bug in the IPython/Jupyter display integration where display observers could be garbage-collected before they had a chance to update.

### Documentation

Added an interactive Playground to the docs, powered by Pyodide and CodeMirror, so you can try `signified` right in your browser.

!!! warning "Deprecations"

    Deprecated functions:

      - `Computed(..., dependencies=...)` — the `dependencies` argument is now ignored. Dependencies are automatically inferred from reactive reads during evaluation.
      - `@reactive_method(...)` — use `@computed` instead. Any dependency-name arguments are also ignored.

    Deprecated several methods

      - `x.as_bool(...)` - Will eventually be removed entirely. Use `computed(bool)(x)` instead.
      - `x.contains(...)` - Use `x.rx.contains` instead.
      - `x.eq(...)` - Use `x.rx.eq` instead
      - `x.where(...)` - Use `x.rx.where` instead
      - `x.is_not(...)` - Use `x.rx.is_not` instead

## 0.2.7

- Significantly improved type inference across a wide range of methods.
- Plugins are now disabled by default — set `SIGNIFIED_ENABLE_HOOKS=1` to re-enable them.
- Several performance improvements.
- Expanded documentation.
- Migrated CI to `uv`.

!!! danger "Breaking Changes"

    - Plugins are now disabled by default.
    - `OrderedSet` and `OrderedWeakRefSet` have been renamed to `_OrderedSet` and `_OrderedWeakRefSet`. These were always internal types.

## 0.2.6

- Fixed packaging so NumPy is truly optional.
- Fixed Python 3.14 compatibility.
- Expanded the CI test matrix to cover newer Python versions.

## 0.2.5

- Improved weak-reference handling in the reactive observer internals.
- Updated core/type integration around weakref sets.
- Minor release metadata updates.

## 0.2.4

- Made IPython an optional dependency.
- Removed the hard NumPy dependency from the base install.
- Updated core/display logic to handle optional imports.

## 0.2.3

- Fixed a runtime typing issue for generic forward references (`ReactiveValue`/`HasValue`).
- Added and expanded API documentation pages and updated MkDocs configuration.
- Updated docs deployment workflow.

## 0.2.2

- Refactored the implementation into smaller, focused modules: `core`, `ops`, `display`, `types`, and `utils`.
- Removed the old monolithic layout.
- Updated docs and test scaffolding to match.

## 0.2.1

- Fixed `deep_unref` to avoid coercing unknown iterables into lists.
- Minor packaging and version metadata adjustments.

## 0.2.0

- Added a plugin system (`signified.plugins`) with examples.
- Added `deep_unref`, memory/performance improvements via `__slots__`, and typing improvements.
- Substantially expanded docs: usage guides, limitations, plugin docs, changelog, and theme updates.

## 0.1.5

- Major expansion of the core reactive implementation and type-inference coverage.
- Improved observe/unobserve and change-detection robustness.
- Release and docs workflow improvements.

## 0.1.4

- Repackaged the project into a `src/signified/` layout.
- Ensured `py.typed` is included in the package.
- Minor README and metadata cleanup.

## 0.1.3

- Improved README and docs landing content.
- Fixed MkDocs configuration issues.
- Minor source and metadata tweaks.

## 0.1.2

- Added support for Python 3.9+.
- Added broad tests for signals, computed values, reactive methods, and type inference.
- Added CI test workflow and moved to a `src/` layout.

## 0.1.1

- Fixed package naming and docs after the project rename.
- Updated project URLs and version metadata.
- Updated changelog entries for the rename transition.

## 0.1.0

- Initial tagged release as `signified`.
