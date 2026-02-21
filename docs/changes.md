---
hide:
  - navigation
---
# Change Log

This page summarizes key changes by diffing adjacent tagged releases.

## 0.3.0

- Reworked `Computed` to use dynamic dependency tracking with lazy recomputation on read.
- Added dependency version tracking so stale markers can be cleared without unnecessary downstream recomputes when derived values stay the same.
- Improved change detection for `Signal.value` updates:
  - callables now use identity checks,
  - ambiguous array-like equality uses all-elements semantics, and
  - `NaN -> NaN` is treated as unchanged.
- Improved mutation invalidation/versioning for `Signal` attribute/item assignments and aligned `deep_unref`/`unref` behavior with runtime dependency tracking.
- Fixed an IPython display observer lifetime bug where observers could be garbage-collected too early.
- Added an interactive docs Playground page (Pyodide + Web Worker + CodeMirror) and updated docs publish triggers for both `v*` and `*.*.*` tags.

Deprecations:
- `Computed(..., dependencies=...)` is deprecated and ignored; dependencies are inferred from reactive reads during evaluation.
- `@reactive_method(...)` is deprecated; use `@computed` instead (dependency-name arguments are ignored).

## 0.2.7

- Significantly improve type inference for a variety of methods.
- Disable plugins by default (now enabled via environment variable, `SIGNIFIED_ENABLE_HOOKS=1`)
- Several performance improvements.
- Expand documentation.
- Migrate CI to `uv`

Breaking Changes:
- Plugins now disabled by default.
- Renamed `OrderedSet` and `OrderedWeakRefSet` to `_OrderedSet` and `_OrderedWeakRefSet`. (You shouldn't be using these anyways...)

## 0.2.6

- Fixed packaging so NumPy is truly optional.
- Fixed Python 3.14 compatibility behavior.
- Expanded/updated CI test matrix for newer Python versions.

## 0.2.5

- Improved weak-reference handling in the reactive observer internals.
- Updated core/type integration around weakref sets.
- Minor release metadata/version updates.

## 0.2.4

- Made IPython an optional dependency.
- Removed hard NumPy dependency from base install requirements.
- Updated core/display logic to support optional imports.

## 0.2.3

- Fixed runtime typing issue for generic forward references (`ReactiveValue`/`HasValue` usage).
- Added/expanded API documentation pages and MkDocs configuration.
- Updated docs deployment workflow.

## 0.2.2

- Refactored the implementation into smaller modules (`core`, `ops`, `display`, `types`, `utils`).
- Removed old monolithic implementation layout.
- Updated docs/test scaffolding to match the split structure.

## 0.2.1

- Fixed `deep_unref` behavior to avoid coercing unknown iterables into lists.
- Minor packaging/version metadata adjustments.

## 0.2.0

- Added plugin system support (`signified.plugins`) and plugin examples.
- Added `deep_unref`, memory/performance cleanup (`__slots__`), and typing improvements.
- Substantially expanded docs (`usage`, `limitations`, `plugins`, changelog, theme updates).

## 0.1.5

- Major expansion of core reactive implementation and type-inference coverage.
- Improved observe/unobserve and change-detection robustness.
- Added release/docs workflow improvements and changelog updates.

## 0.1.4

- Repackaged project into `src/signified/` package layout.
- Ensured `py.typed` ships from package directory.
- Minor README/metadata cleanup.

## 0.1.3

- Improved README and docs landing content.
- Fixed MkDocs configuration issues.
- Minor source and metadata tweaks.

## 0.1.2

- Added support for Python versions `>=3.9` (at that time).
- Added broad tests for signals/computed/reactive methods/type inference.
- Added/updated CI test workflow and moved to `src/` source layout.

## 0.1.1

- Fixed package naming/docs after rename.
- Updated project URLs and version metadata.
- Updated changelog entries for the rename transition.

## 0.1.0

- Initial tagged release as `signified`.
