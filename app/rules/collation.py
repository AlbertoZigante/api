"""JS `String.prototype.localeCompare` for the ids / piece codes the planner sorts by.

The JS planner breaks every tie with `a.localeCompare(b)` (ICU collation): letters compare case-insensitively
first (a < B < c), digits sort before letters, punctuation before digits, and only when the strings are equal
ignoring case does the lower-case letter win. Python's `<` is code-point order (all capitals before all
lower-case), which would reorder steps for codes such as `Left` vs `back`. This reproduces the ICU order for
ASCII (verified against node's Intl by tests/test_assembly_differential.py).
"""
from __future__ import annotations

from functools import cmp_to_key

# ICU root collation order of the ASCII non-alphanumerics (whitespace first, symbols, then digits, then letters)
_PUNCT = " _-,;:!?.'\"()[]{}@*/\\&#%`^+<=>|~$"


def _primary(ch: str) -> tuple[int, int | str]:
    if ch.isalpha():
        return (3, ch.lower())
    if ch.isdigit():
        return (2, ch)
    idx = _PUNCT.find(ch)
    return (1, idx if idx >= 0 else 1000 + ord(ch))


def locale_compare(a: str, b: str) -> int:
    pa, pb = [_primary(c) for c in a], [_primary(c) for c in b]
    if pa != pb:
        return -1 if pa < pb else 1
    for ca, cb in zip(a, b, strict=True):  # equal ignoring case: lower-case first
        if ca != cb:
            return -1 if ca.islower() else 1
    return 0


locale_key = cmp_to_key(locale_compare)
