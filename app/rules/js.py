"""Small JavaScript semantics the ports must reproduce exactly."""
from __future__ import annotations

import math


def js_round(x: float) -> int:
    """JavaScript Math.round: halves round UP (Python's round() is banker's: round(0.5) == 0)."""
    return math.floor(x + 0.5)
