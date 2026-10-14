"""key3d's `at`, `until` and `after`, built on `signified.sample()`.

Checks them against evaluating each frame directly, then times the scenes
from key3d's feature request: followers of one moving cube, and followers of
a 100-cube group.

Usage:
    uv run python benchmarks/time_helpers.py
"""

import random
import timeit

from signified import Computed, Signal, computed, is_reactive, sample

# --- The helpers, as key3d would write them --------------------------------


def at(value, frame, *, frame_signal):
    """`value` as it is at `frame`, on every frame."""
    if not is_reactive(value):
        return value
    return sample(value, frame_signal, frame)


def until(value, frame, *, frame_signal):
    """Live up to `frame`, then held where it was at `frame`."""
    if not is_reactive(value):
        return value
    return sample(value, frame_signal, computed(lambda f: min(f, frame))(frame_signal))


def after(value, frame, *, frame_signal):
    """Held at its value at `frame` before `frame`, then live."""
    if not is_reactive(value):
        return value
    return sample(value, frame_signal, computed(lambda f: max(f, frame))(frame_signal))


# --- A scene: cubes that move with the frame, sized by a slider ------------


def cube_box(k, f, size):
    x = k + 0.1 * f * (1 + k % 3)
    return (x - size, x + size)


def make_scene(cubes=100):
    frame = Signal(0)
    size = Signal(1.0)
    boxes = [computed(lambda f, s, k=k: cube_box(k, f, s))(frame, size) for k in range(cubes)]
    group = Computed(lambda: (min(b.value[0] for b in boxes), max(b.value[1] for b in boxes)))
    return frame, size, boxes, group


def group_box(f, size, cubes=100):
    lows, highs = zip(*(cube_box(k, f, size) for k in range(cubes)))
    return (min(lows), max(highs))


def follower(target):
    """Something placed just right of `target`, like `label.next_to(target, RIGHT)`."""
    return computed(lambda box: box[1] + 0.5)(target)


# --- Correctness ------------------------------------------------------------


def check():
    frame, size, boxes, group = make_scene()
    cube = boxes[1]
    helpers = {
        "at 45": (at(cube, 45, frame_signal=frame), lambda f: 45),
        "until 45": (until(cube, 45, frame_signal=frame), lambda f: min(f, 45)),
        "after 45": (after(cube, 45, frame_signal=frame), lambda f: max(f, 45)),
        "after(until(60), 40)": (
            after(until(cube, 60, frame_signal=frame), 40, frame_signal=frame),
            lambda f: min(max(f, 40), 60),
        ),
        "group at 45": (at(group, 45, frame_signal=frame), lambda f: 45),
    }
    followers = {name: follower(node) for name, (node, _) in helpers.items()}
    frames = list(range(90)) + list(range(89, -1, -1)) + random.Random(0).sample(range(90), 90)
    for s in (1.0, 2.0):  # the second pass runs after a slider edit
        size.value = s
        for f in frames:
            frame.value = f
            for name, (_, when) in helpers.items():
                box = group_box(when(f), s) if name.startswith("group") else cube_box(1, when(f), s)
                assert followers[name].value == box[1] + 0.5, (name, f, s)
            assert cube.value == cube_box(1, f, s)
    print("correct on every frame, forward, backward and shuffled, before and after a slider edit")


# --- Cost per frame ---------------------------------------------------------


def per_frame_ms(frame, readers, frames=range(90)):
    for f in frames:  # first reads, so the timing below is steady state
        frame.value = f
        for reader in readers:
            reader.value

    def play():
        for f in frames:
            frame.value = f
            for reader in readers:
                reader.value

    return min(timeit.repeat(play, number=1, repeat=5)) / len(frames) * 1e3


def eager(value, f, frame):
    """key3d's current approach: read the frozen value once, when the line runs."""
    with frame.at(f):
        return value.value


def timings():
    rows = []

    frame, _, boxes, _ = make_scene(cubes=2)
    cube = boxes[1]
    rows.append(("200 followers of a moving cube, live", per_frame_ms(frame, [follower(cube) for _ in range(200)])))
    rows.append(
        ("  eager at 45 (read once)", per_frame_ms(frame, [follower(eager(cube, 45, frame)) for _ in range(200)]))
    )
    for name, helper in (("at", at), ("until", until), ("after", after)):
        readers = [follower(helper(cube, 45, frame_signal=frame)) for _ in range(200)]
        rows.append((f"  {name} 45, one sample per follower", per_frame_ms(frame, readers)))
        shared = helper(cube, 45, frame_signal=frame)
        rows.append((f"  {name} 45, one shared sample", per_frame_ms(frame, [follower(shared) for _ in range(200)])))

    frame, _, _, group = make_scene()
    rows.append(("50 followers of a 100-cube group, live", per_frame_ms(frame, [follower(group) for _ in range(50)])))
    rows.append(
        ("  eager at 45 (read once)", per_frame_ms(frame, [follower(eager(group, 45, frame)) for _ in range(50)]))
    )
    shared = at(group, 45, frame_signal=frame)
    rows.append(("  at 45, one shared sample", per_frame_ms(frame, [follower(shared) for _ in range(50)])))
    readers = [follower(at(group, 45, frame_signal=frame)) for _ in range(50)]
    rows.append(("  at 45, one sample per follower", per_frame_ms(frame, readers)))

    frame, _, _, group = make_scene()
    group.value
    first = timeit.timeit(lambda: at(group, 45, frame_signal=frame).value, number=20) / 20 * 1e3
    live = timeit.timeit(lambda: (setattr(frame, "value", frame.value + 1), group.value), number=20) / 20 * 1e3
    rows.append(("first read of at(group, 45)", first))
    rows.append(("  the group live on a new frame, for scale", live))

    for label, ms in rows:
        print(f"{label:<46} {ms:8.3f} ms")


if __name__ == "__main__":
    check()
    print()
    timings()
