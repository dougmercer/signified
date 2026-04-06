import asyncio

from signified import Computed, Signal, async_effect, resource


async def _drain_loop(turns: int = 3) -> None:
    for _ in range(turns):
        await asyncio.sleep(0)


def test_async_effect_runs_immediately_and_on_updates():
    async def scenario() -> None:
        source = Signal(1)
        seen: list[int] = []
        tick = asyncio.Event()

        @async_effect
        async def log(value: int) -> None:
            seen.append(value)
            tick.set()

        runner = log(source)

        await asyncio.wait_for(tick.wait(), 1)
        tick.clear()

        source.value = 2
        await asyncio.wait_for(tick.wait(), 1)

        runner.dispose()
        source.value = 3
        await _drain_loop()

        assert seen == [1, 2]
        assert runner.running == False  # noqa: E712
        assert runner.error is None

    asyncio.run(scenario())


def test_resource_is_reactive_and_switches_to_latest_result():
    async def scenario() -> None:
        query = Signal("a")
        gates = {"a": asyncio.Event(), "b": asyncio.Event()}
        started: list[str] = []

        @resource
        async def load(value: str) -> str:
            started.append(value)
            await gates[value].wait()
            return value.upper()

        result = load(query)
        summary = Computed(lambda: "loading" if result.loading else result.value or "empty")

        await _drain_loop()
        assert started == ["a"]
        assert result.loading == True  # noqa: E712
        assert result.status == "loading"
        assert summary.value == "loading"

        query.value = "b"
        await _drain_loop()

        assert started == ["a", "b"]
        assert result.loading == True  # noqa: E712
        assert result.status == "loading"
        assert result.value is None

        gates["b"].set()
        await _drain_loop()

        assert result.value == "B"
        assert result.error is None
        assert result.loading == False  # noqa: E712
        assert result.status == "ready"
        assert summary.value == "B"

        gates["a"].set()
        await _drain_loop()

        assert result.value == "B"
        result.dispose()

    asyncio.run(scenario())


def test_resource_keeps_last_value_while_reloading():
    async def scenario() -> None:
        selected = Signal(1)
        gates = {1: asyncio.Event(), 2: asyncio.Event()}

        @resource
        async def load(value: int) -> int:
            await gates[value].wait()
            return value * 10

        result = load(selected)

        await _drain_loop()
        gates[1].set()
        await _drain_loop()

        assert result.value == 10
        assert result.status == "ready"

        selected.value = 2
        await _drain_loop()

        assert result.loading == True  # noqa: E712
        assert result.status == "loading"
        assert result.value == 10

        gates[2].set()
        await _drain_loop()

        assert result.value == 20
        assert result.loading == False  # noqa: E712
        assert result.status == "ready"
        result.dispose()

    asyncio.run(scenario())


def test_resource_dispose_cancels_inflight_request():
    async def scenario() -> None:
        gate = asyncio.Event()

        @resource
        async def load() -> int:
            await gate.wait()
            return 42

        result = load()
        await _drain_loop()

        assert result.loading == True  # noqa: E712
        result.dispose()
        gate.set()
        await _drain_loop()

        assert result.loading == False  # noqa: E712
        assert result.status == "idle"
        assert result.value is None

    asyncio.run(scenario())
