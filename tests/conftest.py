import pytest

from signified import Computed, Signal, computed


@pytest.fixture(autouse=True)
def add_signal(doctest_namespace):
    doctest_namespace["Signal"] = Signal


@pytest.fixture(autouse=True)
def add_computed(doctest_namespace):
    doctest_namespace["Computed"] = Computed
    doctest_namespace["computed"] = computed
