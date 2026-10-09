"""Run every spike test against the current Python engine and the Rust core.

The Python engine is the reference: a test's expected values must hold for
both. The `rust` parameter fails with ImportError until `signified._spike`
exists, which is the expected red state before Task 3.
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

    from signified import _spike

    # Operators on the shared mixin build nodes through `_computed_call`; point
    # them at the Rust engine for this test only.
    monkeypatch.setattr(_mixin, "_computed_call", _spike.computed_call)
    return SimpleNamespace(
        name="rust",
        Signal=_spike.Signal,
        Computed=_spike.Computed,
        untracked=_spike.untracked,
        observer_count=lambda source: source._observer_count(),
    )
