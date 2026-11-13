"""Every (stage x design) of the frozen JS goldens. Ported stages must match; stages not ported
yet are STRICT xfails (see golden_harness.py)."""
import pytest

from tests.golden_harness import STAGES, assert_matches, designs, load

CASES = [pytest.param(s, d, id=f"{s}-{d}") for s in STAGES for d in designs()]


@pytest.mark.parametrize("stage,design", CASES)
def test_stage_matches_golden(client, request, stage, design):
    spec = STAGES[stage]
    if not spec.ported:
        request.applymarker(pytest.mark.xfail(strict=True, reason=f"not ported yet (phase {spec.phase})"))
    actual = spec.run(client, design)
    assert_matches(actual, load(design, spec.expected), spec.abs_tol)
