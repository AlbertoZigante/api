from tests.conftest import panel


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_materials(client):
    r = client.get("/v1/catalog/materials")
    assert r.status_code == 200
    assert r.json()[0]["sheetWidthMm"] == 2440


def test_bom_camel_case_roundtrip(client):
    body = {"panels": [panel("A", 400, 700, groupId="g", isBoxPanel=True, bandedEdges=["left"])]}
    r = client.post("/v1/bom", json=body)
    assert r.status_code == 200
    row = r.json()["rows"][0]
    assert row["widthMm"] == 400 and row["assembly"] == "Box 1" and row["bandedEdgesLabel"] == "L"


def test_nesting(client):
    r = client.post("/v1/nesting", json={"panels": [panel("A", 400, 700), panel("B", 400, 700)]})
    assert r.status_code == 200
    j = r.json()
    assert j["summary"]["totals"]["sheetsUsed"] == 1
    assert j["results"][0]["sheets"][0]["placements"][0]["finishedWidthMm"] in (400, 700)


def test_bad_payload_422(client):
    assert client.post("/v1/bom", json={"panels": [{"id": "x"}]}).status_code == 422
