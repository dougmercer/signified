"""A/B key3d's `moving` scene: graph pass, full frame, and build time per signified build.

Run from the key3d repo root with the build to test on PYTHONPATH, e.g.:
    PYTHONPATH=<signified>/src:<dir with mypy_extensions.py> .venv/bin/python <this file>
"""

import gc
import json
import sys
import time

sys.path.insert(0, "benchmarks")

import frame_throughput as ft  # noqa: E402  (key3d's benchmarks/frame_throughput.py)
from key3d.objects.base import Base  # noqa: E402

import signified._reactive as R  # noqa: E402

FRAMES = 48

start = time.perf_counter()
scene = ft.moving(320, FRAMES)
build = time.perf_counter() - start
start = time.perf_counter()
scene.read_frame_rgba(0)
first = time.perf_counter() - start
objs = [o for o in gc.get_objects() if isinstance(o, Base)]


def graph_pass():
    for f in range(1, FRAMES):
        scene.frame.value = f
        for o in objs:
            o.matrix.value


def full_pass():
    for f in range(1, FRAMES):
        scene.read_frame_rgba(f)


def best(fn, repeat):
    fn()
    times = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)
    return min(times) / (FRAMES - 1) * 1000


print(
    json.dumps(
        {
            "module": R.__file__.rsplit("/", 1)[-1],
            "scene_build_s": build,
            "first_frame_s": first,
            "graph_ms_per_frame": best(graph_pass, 7),
            "full_ms_per_frame": best(full_pass, 3),
        }
    )
)
