import pytest
from fastapi.testclient import TestClient

from app.catalog.loader import load_materials
from app.main import app


@pytest.fixture(scope="session")
def catalog():
    return load_materials()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def panel(id, w, h, material="Melamine White 18mm", thickness=18, **kw):
    return {"id": id, "name": id, "pieceCode": f"P-{id}", "width": w, "height": h,
            "thickness": thickness, "material": material, **kw}
