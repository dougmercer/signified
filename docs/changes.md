---
hide:
  - navigation
---
# Change Log

This page summarizes notable changes across releases.

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

  - is_not
  - contains
  - eq
  - where

### Bug Fixes

Fixed a bug in the IPython/Jupyter display integration where display observers could be garbage-collected before they had a chance to update.

### Documentation

Added an interactive Playground to the docs, powered by Pyodide and CodeMirror, so you can try `signified` right in your browser.

!!! warning "Deprecations"

    - `Computed(..., dependencies=...)` — the `dependencies` argument is now ignored. Dependencies are automatically inferred from reactive reads during evaluation.
    - `@reactive_method(...)` — use `@computed` instead. Any dependency-name arguments are also ignored.
    - Deprecated several methods
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
