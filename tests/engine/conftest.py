"""Run every engine test against the Python engine and the Rust core.

The Python engine is the reference: a test's expected values must hold for
both.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from signified import _mixin


@pytest.fixture(params=["python", "rust"])
def rx(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    if request.param == "python":
        from signified import Computed, Signal, untracked

        def observer_count(source: object) -> int:
            return sum(1 for _ in source._observers.iter_alive())  # type: ignore[attr-defined]

        return SimpleNamespace(
            name="python", Signal=Signal, Computed=Computed, untracked=untracked, observer_count=observer_count
        )

    from signified import _native

    # Operators on the shared mixin build nodes through `_computed_call`; point
    # them at the Rust engine for this test only.
    monkeypatch.setattr(_mixin, "_computed_call", _native.computed_call)
    return SimpleNamespace(
        name="rust",
        Signal=_native.Signal,
        Computed=_native.Computed,
        untracked=_native.untracked,
        observer_count=lambda source: source._observer_count(),
    )
