---
hide:
  - navigation
---
# Change Log

## 0.3.0

- Add rx namespace which includes several methods.
  - map (new)
  - tap (new)
  - len (new)
  - is_ (new)
  - is_not
  - in_ (new)
  - contains
  - eq
  - where

Deprecated:
  - `x.as_bool(...)` - Will eventually be removed entirely. Use `computed(bool)(x)` instead.
  - `x.contains(...)` - Use `x.rx.contains` instead.
  - `x.eq(...)` - Use `x.rx.eq` instead
  - `x.where(...)` - Use `x.rx.where` instead
  - `x.is_not(...)` - Use `x.rx.is_not` instead

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
