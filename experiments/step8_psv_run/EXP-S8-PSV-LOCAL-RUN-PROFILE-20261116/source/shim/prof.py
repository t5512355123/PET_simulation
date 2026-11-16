"""Exclusive (self-time) section timer. Nested sections subtract from their parent."""
import time, collections
from contextlib import contextmanager

acc = collections.defaultdict(float)
cnt = collections.defaultdict(int)
_stack = []


@contextmanager
def sec(name):
    t0 = time.perf_counter()
    _stack.append([name, 0.0])
    try:
        yield
    finally:
        n, child = _stack.pop()
        dt = time.perf_counter() - t0
        acc[n] += dt - child
        cnt[n] += 1
        if _stack:
            _stack[-1][1] += dt


def snapshot():
    return dict(acc)
