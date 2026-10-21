"""Compare frozen builds with the same interpreter and interleaved rounds.

Each root must contain a signified/ package, including its compiled extension.
For example, copy src/signified after building each variant with maturin.

    python benchmarks/watcher.py \
        --variant baseline=.venv/watcher-variants/baseline \
        --variant optimized=src \
        --output watcher_results.json

Build each revision with `maturin develop --release` before copying its package.
All timing results are nanoseconds per operation, median of three repetitions;
the parent reports medians across three interleaved subprocess rounds. Memory
is a separate fresh process's peak RSS increase, including keys and watches.
"""

import argparse
import gc
import json
import os
import platform
import resource
import statistics
import subprocess
import sys
import time
import timeit
from pathlib import Path


def measure():
    from signified import Computed, Signal, Watcher

    def ns(fn, number):
        fn()
        return statistics.median(timeit.repeat(fn, number=number, repeat=3)) * 1e9 / number

    result = {}
    for n in (400, 10_000, 100_000):
        source = Signal(0)
        keys = [object() for _ in range(n)]
        watcher = Watcher()
        for key in keys:
            watcher.watch(source, key)
        missing = object()
        target = keys[n // 2]

        def rewatch(watcher=watcher, source=source, target=target):
            watcher.unwatch(target)
            watcher.watch(source, target)

        result[f"idle/{n}"] = ns(watcher.changed, 100_000)
        result[f"len/{n}"] = ns(lambda: len(watcher), 1_000)
        result[f"unwatch_missing/{n}"] = ns(lambda: watcher.unwatch(missing), 200)
        result[f"rewatch/{n}"] = ns(rewatch, 200)
        del rewatch, watcher, source, keys, target, key
        gc.collect()

    for kind in ("object", "string", "shared"):
        n = 10_000
        source = Signal(0)
        keys = [f"row{i}" if kind == "string" else object() for i in range(n)]
        if kind == "shared":
            keys = [keys[0]] * n
        samples = []
        for _ in range(5):
            watcher = Watcher()
            before = time.perf_counter_ns()
            for key in keys:
                watcher.watch(source, key)
            samples.append((time.perf_counter_ns() - before) / n)
            del watcher
        result[f"register_{kind}/{n}"] = statistics.median(samples)

    for mode in ("signal", "computed", "equal", "sparse"):
        for n in (400, 4_000):
            source = Signal(0)
            static = Signal(0)
            watcher = Watcher()
            for i in range(n):
                if mode == "signal":
                    value = source
                elif mode == "sparse":
                    value = source if i == 0 else static
                elif mode == "computed":
                    value = Computed(lambda source=source: source.value)
                else:
                    value = Computed(lambda source=source: min(source.value, 0))
                watcher.watch(value, object())
            step = 0

            def frame():
                nonlocal step
                step += 1
                source.value = step
                return watcher.changed()

            result[f"write_poll_{mode}/{n}"] = ns(frame, 200)
            del watcher, source, static, value
            gc.collect()

    for n in (1_000, 4_000, 8_000):
        source = Signal(0)
        watcher = Watcher()
        for _ in range(n):
            watcher.watch(source, object())

        def compute(source=source):
            if source.value:
                raise KeyboardInterrupt
            return 0

        watcher.watch(Computed(compute), object())
        source.value = 1

        def cancel():
            try:
                watcher.changed()
            except KeyboardInterrupt:
                pass

        result[f"cancel_restore/{n}"] = ns(cancel, 3)
    return result


def memory():
    from signified import Signal, Watcher

    gc.collect()
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    source = Signal(0)
    watcher = Watcher()
    for _ in range(200_000):
        watcher.watch(source, object())
    after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    multiplier = 1 if sys.platform == "darwin" else 1024
    return {"rss_growth_bytes": (after - before) * multiplier, "watches": len(watcher)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--variant", action="append", default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--child", choices=("timings", "memory"))
    args = parser.parse_args()
    if args.child:
        print(json.dumps(measure() if args.child == "timings" else memory()))
        return
    variants = {name: str(Path(root).resolve()) for name, root in (v.split("=", 1) for v in args.variant)}
    runs = {name: [] for name in variants}
    memory_runs = {name: [] for name in variants}

    def run(name, kind):
        env = dict(os.environ, PYTHONPATH=variants[name])
        child = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--child", kind],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(child.stdout)

    names = list(variants)
    for round_index in range(3):
        order = names[round_index:] + names[:round_index]
        for name in order:
            runs[name].append(run(name, "timings"))
            memory_runs[name].append(run(name, "memory"))
            print(f"round {round_index + 1}: {name}", flush=True)
    results = {
        "python": sys.version,
        "platform": platform.platform(),
        "variants": variants,
        "median_ns": {
            name: {key: statistics.median(row[key] for row in rows) for key in rows[0]} for name, rows in runs.items()
        },
        "memory": memory_runs,
        "raw_ns": runs,
    }
    if args.output:
        args.output.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results["median_ns"], indent=2))


if __name__ == "__main__":
    main()
