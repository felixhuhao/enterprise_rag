"""Small time measurement helpers."""

import time


def tick_ms(t0: float) -> int:
    return round((time.monotonic() - t0) * 1000)
