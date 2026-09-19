---
search:
  exclude: true
---

# Known limitations

These notes have moved into the guides, beside the examples they apply to.

## Type Inference

See [Type checkers](type-checkers.md) for recommendations and typing limitations.

## In-place mutation

See [Lists and dictionaries](usage.md#collections-and-item-assignment) for
replacement, item assignment, and notifying after a change to the raw object.

## Scheduling and snapshots

See [How updates work](compute-contract.md#batching-and-effect-lifetime) for
batching and thread restrictions, and [Nested values](resolution.md#supported-values)
for the limits of copying and serialization.

## Plugin Hooks Are Opt-In

See [Enable plugins](plugins.md#enable-plugins) for installation and setup.
