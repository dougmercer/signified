# Change Log

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
