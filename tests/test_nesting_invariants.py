"""Phase 6: invariants on every golden design, plus property-based tests on random inputs."""
import json

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.services.nesting import nest_pieces
from tests.golden_harness import designs, load
from tests.nesting_invariants import cut_list_violations, nest_pieces_violations


# ------------------------------------------------------------------ real designs (via the API)
@pytest.mark.parametrize("design", designs("panels"))
def test_golden_designs_satisfy_all_invariants(client, catalog, design):
    r = client.post("/v1/nesting", json={"panels": load(design, "panels"), "options": {}})
    assert r.status_code == 200
    kerfs = {m.name: (m.kerf_mm if m.kerf_mm is not None else 3.0) for m in catalog}
    assert cut_list_violations(r.json(), kerfs) == []


# ------------------------------------------------------------------ random inputs
def piece(i, w, h, rotatable):
    return {"id": f"p{i}", "label": f"p{i}", "widthMm": w, "heightMm": h, "rotatable": rotatable,
            "finishedWidthMm": w, "finishedHeightMm": h}


@st.composite
def instances(draw):
    sw = draw(st.integers(300, 3000))
    sh = draw(st.integers(300, 3000))
    kerf = draw(st.sampled_from([0, 0.5, 2, 3, 3.2, 8]))
    n = draw(st.integers(0, 40))
    # up to 1.3x the stock: a share of oversize pieces must come back as `unplaced`
    dim = st.one_of(st.integers(1, max(sw, sh)), st.floats(1, max(sw, sh) * 1.3, allow_nan=False, allow_infinity=False))
    pieces = [piece(i, draw(dim), draw(dim), draw(st.booleans())) for i in range(n)]
    return pieces, {"widthMm": float(sw), "heightMm": float(sh)}, float(kerf)


PROPERTY = settings(max_examples=250, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@PROPERTY
@given(instances())
def test_random_instances_satisfy_all_invariants(inst):
    pieces, stock, kerf = inst
    result = nest_pieces(pieces, stock, kerf)
    assert nest_pieces_violations(pieces, stock, kerf, result) == []


@PROPERTY
@given(instances())
def test_nesting_is_deterministic(inst):
    pieces, stock, kerf = inst
    first = json.dumps(nest_pieces(pieces, stock, kerf), sort_keys=True)
    second = json.dumps(nest_pieces([dict(p) for p in pieces], dict(stock), kerf), sort_keys=True)
    assert first == second


@PROPERTY
@given(instances())
def test_nesting_does_not_mutate_its_input(inst):
    pieces, stock, kerf = inst
    before = json.dumps([pieces, stock], sort_keys=True)
    nest_pieces(pieces, stock, kerf)
    assert json.dumps([pieces, stock], sort_keys=True) == before


def test_checker_catches_overlap_kerf_and_lost_pieces():
    """The invariant checker must itself be able to fail."""
    stock = {"widthMm": 1000.0, "heightMm": 1000.0}
    pieces = [piece(0, 100, 100, True), piece(1, 100, 100, True)]
    good = nest_pieces(pieces, stock, 3)
    assert nest_pieces_violations(pieces, stock, 3, good) == []

    def tampered(mutate):
        bad = json.loads(json.dumps(good))
        mutate(bad)
        return nest_pieces_violations(pieces, stock, 3, bad)

    pl = lambda r: r["sheets"][0]["placements"]  # noqa: E731
    assert any("closer than kerf" in v for v in tampered(lambda r: pl(r)[1].update(xMm=pl(r)[0]["xMm"] + 101, yMm=pl(r)[0]["yMm"])))
    assert any("outside" in v for v in tampered(lambda r: pl(r)[0].update(xMm=950)))
    assert any("lost" in v for v in tampered(lambda r: pl(r).pop()))
    assert any("rotated although grain" in v for v in nest_pieces_violations(
        [piece(0, 100, 200, False), piece(1, 100, 100, True)], stock, 3,
        {"sheets": [{"sheetIndex": 0, "widthMm": 1000.0, "heightMm": 1000.0, "usedAreaM2": 0.03, "totalAreaM2": 1.0,
                     "utilization": 0.03, "placements": [
                         {"pieceId": "p0", "xMm": 0, "yMm": 0, "widthMm": 200, "heightMm": 100, "rotated": True},
                         {"pieceId": "p1", "xMm": 300, "yMm": 0, "widthMm": 100, "heightMm": 100, "rotated": False}]}],
         "unplaced": []}))
