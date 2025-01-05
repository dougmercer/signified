# Change Log

## 0.2.0

New Features

* Add a plugin system

Performance

* Use slots to save memory

Bugfixes

* Fix bug in unobserve method, replacing subscribe with unsubscribe
* Add a deep_unref function to handle some nested signal edge cases

Type Inference

* Improve reactive_method's ability to properly infer types

CI/CD

* Make ruff actually enforce isort-like imports

Docs

* Improve Usage section of the docs
* Add a Limitations page to the docs
* Add a plugins page to the docs

## 0.1.5

Features

* Added ``__setitem__`` and ``__setattr`` methods for generating reactive values.

Docs

* Added examples to docstrings (in doctest format).

Bug Fixes

* Under several conditions, Reactive values generated from ``__call__`` and ``__getitem__`` weren't updating when an upstream observable was updated.

Typing

* Improve type inference for ``__call__`` generated reactive values.

## 0.1.4
Minor changes to packaging and documentation

## 0.1.1
Initial release.
