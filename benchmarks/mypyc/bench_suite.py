"""Run tests/test_benchmarks.py with a timeit-based `benchmark` stand-in; print JSON of ns/call.

Usage: python bench_suite.py tests/test_benchmarks.py > results.json
(Select the signified build under test with PYTHONPATH.)
"""

import importlib.util
import inspect
import json
import sys
import timeit

spec = importlib.util.spec_from_file_location("bench", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class Bench:
    def __call__(self, fn, *args, **kwargs):
        call = lambda: fn(*args, **kwargs)  # noqa: E731
        call()
        timer = timeit.Timer(call)
        number, _ = timer.autorange()
        number = max(1, number // 2)
        self.ns = min(timer.repeat(repeat=7, number=number)) / number * 1e9
        return call()


import signified._reactive as r  # noqa: E402  (after loading the benchmarks module)

results = {"_module": r.__file__.rsplit("/", 1)[-1]}
for name, fn in inspect.getmembers(mod, inspect.isfunction):
    if not name.startswith("test_bench"):
        continue
    b = Bench()
    fn(b)
    results[name.removeprefix("test_bench_").removesuffix("_v1")] = b.ns
print(json.dumps(results))
