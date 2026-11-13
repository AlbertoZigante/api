"""The harness itself must catch what it claims to catch."""
import pytest

from tests.golden_harness import STAGES, assert_matches, deep_diff, designs


def test_equal_structures_have_no_diff():
    assert deep_diff({"a": [1, 2.0, {"b": None}], "c": "x", "d": True}, {"a": [1, 2.0, {"b": None}], "c": "x", "d": True}) == []


def test_float_tolerance():
    assert deep_diff({"v": 1.0004}, {"v": 1.0}, abs_tol=1e-3) == []
    assert deep_diff({"v": 1.002}, {"v": 1.0}, abs_tol=1e-3) != []
    assert deep_diff(3, 3.0) == []  # int vs float from JSON is not a difference


@pytest.mark.parametrize(
    "actual,expected",
    [
        ({"a": 1}, {"a": 1, "b": 2}),           # missing key
        ({"a": 1, "b": 2}, {"a": 1}),           # unexpected key
        ([1, 2], [1, 2, 3]),                    # length
        ({"a": "x"}, {"a": "y"}),               # string
        ({"a": True}, {"a": 1}),                # bool is not a number
        ({"a": None}, {"a": 0}),                # null is not zero
        ({"a": [{"b": 1}]}, {"a": [{"b": 2}]}), # nested
    ],
)
def test_differences_are_detected(actual, expected):
    assert deep_diff(actual, expected) != []
    with pytest.raises(AssertionError):
        assert_matches(actual, expected)


def test_diff_reports_a_useful_path():
    assert deep_diff({"rows": [{"qty": 2}]}, {"rows": [{"qty": 3}]}) == ["$.rows[0].qty: 2 != 3 (tol 0.001)"]


def test_registry_covers_every_golden_stage_file():

    from tests.golden_harness import GOLDEN

    d = designs()[0]
    on_disk = {p.stem for p in (GOLDEN / d).glob("*.json")}
    assert {s.expected for s in STAGES.values()} <= on_disk


def test_phase_assignment():
    ported = {n for n, s in STAGES.items() if s.ported}
    assert ported == {"bom", "nesting"}
