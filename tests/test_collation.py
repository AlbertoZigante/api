"""app.rules.collation.locale_compare must order exactly like JS `localeCompare` (ICU): the planner's tie-breaks decide
the order of steps. The expected signs were produced by node's Intl before the JS engine was deleted (phase 12)."""
import json
from pathlib import Path

import pytest

from app.rules.collation import locale_compare

CASES = json.loads((Path(__file__).parent / "golden" / "collation.json").read_text(encoding="utf-8"))["cases"]


def test_locale_compare_matches_the_frozen_icu_results():
    wrong = [(a, b, s, locale_compare(a, b)) for a, b, s in CASES if locale_compare(a, b) != s]
    assert not wrong, f"{len(wrong)} of {len(CASES)} differ, e.g. {wrong[:5]}"


@pytest.mark.parametrize("a,b,sign", [("a", "B", -1), ("B", "a", 1), ("Left", "back", 1), ("a", "A", -1), ("", "a", -1),
                                      ("1", "a", -1), ("A2", "A10", 1), ("x", "x", 0)])
def test_the_cases_that_matter_for_step_order(a, b, sign):
    assert locale_compare(a, b) == sign
