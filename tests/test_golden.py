"""Every (stage x design) of the frozen goldens must match what the API answers (see golden_harness.py)."""
import pytest

from tests.golden_harness import STAGES, assert_matches, designs, load

CASES = [pytest.param(s, d, id=f"{s}-{d}") for s in STAGES for d in designs(STAGES[s].expected)]


@pytest.mark.parametrize("stage,design", CASES)
def test_stage_matches_golden(client, stage, design):
    spec = STAGES[stage]
    assert_matches(spec.run(client, design), load(design, spec.expected), spec.abs_tol)
