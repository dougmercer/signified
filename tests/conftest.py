import pytest

from signified import Computed, Signal, computed


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--slow",
        action="store_true",
        default=False,
        help="Include slow benchmarks when running with --codspeed.",
    )


def _markexpr_mentions_benchmarks(markexpr: str) -> bool:
    return "benchmark" in markexpr or "slow_benchmark" in markexpr


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Keep benchmarks out of plain pytest runs, but enable fast CodSpeed runs by default."""
    markexpr = getattr(config.option, "markexpr", "") or ""
    is_codspeed_run = bool(getattr(config.option, "codspeed", False))
    include_slow_benchmarks = bool(config.getoption("--slow"))

    selected: list[pytest.Item] = []
    deselected: list[pytest.Item] = []

    if is_codspeed_run:
        if include_slow_benchmarks or _markexpr_mentions_benchmarks(markexpr):
            return
        for item in items:
            if item.get_closest_marker("slow_benchmark") is not None:
                deselected.append(item)
            else:
                selected.append(item)
    else:
        if _markexpr_mentions_benchmarks(markexpr):
            return
        for item in items:
            if item.get_closest_marker("benchmark") is not None:
                deselected.append(item)
            else:
                selected.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected


@pytest.fixture(autouse=True)
def add_signal(doctest_namespace):
    doctest_namespace["Signal"] = Signal


@pytest.fixture(autouse=True)
def add_computed(doctest_namespace):
    doctest_namespace["Computed"] = Computed
    doctest_namespace["computed"] = computed
