---
hide:
  - navigation
---
# Change Log

This page summarizes notable changes across releases.

## 0.5.0

### Deprecations

Functions

* `reactive_method` - Use `computed` instead.
* `as_signal` - Use `as_rx` instead.

Arguments

* `Computed(fn, dependencies=...)` - Use `Computed(fn)` instead.

Public Methods

* `Variable.add_name` - Use `Variable.with_name` instead.
* `Variable.as_bool` - Use `Variable.rx.as_bool` instead.
* `Variable.contains` - Use `Variable.rx.contains` instead.
* `Variable.is_not` - Use `Variable.rx.is_not` instead.
* `Variable.eq` - Use `Variable.rx.eq` instead.
* `Variable.where` - Use `Variable.rx.where` instead.

Plumbing Methods

* `Variable.observe` - Use `Variable._observe` instead.
* `Variable.unobserve` - Use `Variable._unobserve` instead.

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
    - **`NestedValue` removed from public exports**: `from signified import NestedValue` will raise `ImportError`. The type alias is still available in `signified._types` if needed.
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
