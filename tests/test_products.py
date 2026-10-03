from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

APPLE = {"name": "Яблоко", "description": "Гренни Смит", "price": "129.90", "quantity": 50}


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(str(tmp_path / "test.db")))


def test_add_product(client):
    response = client.post("/products", json=APPLE)

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == 1
    assert body["name"] == "Яблоко"
    assert Decimal(body["price"]) == Decimal("129.90")
    assert body["quantity"] == 50


def test_add_product_uses_defaults_for_optional_fields(client):
    response = client.post("/products", json={"name": "Банан", "price": "89"})

    assert response.status_code == 201
    assert response.json()["description"] is None
    assert response.json()["quantity"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"price": "10"},
        {"name": "", "price": "10"},
        {"name": "   ", "price": "10"},
        {"name": "Груша"},
        {"name": "Груша", "price": "0"},
        {"name": "Груша", "price": "-5"},
        {"name": "Груша", "price": "10.999"},
        {"name": "Груша", "price": "10", "quantity": -1},
        {"name": "Груша", "price": "10", "id": 7},
    ],
)
def test_add_product_rejects_invalid_payload(client, payload):
    assert client.post("/products", json=payload).status_code == 422
    assert client.get("/products").json() == []


def test_get_product(client):
    created = client.post("/products", json=APPLE).json()

    response = client.get(f"/products/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_missing_product_returns_404(client):
    assert client.get("/products/42").status_code == 404


def test_update_product(client):
    product_id = client.post("/products", json=APPLE).json()["id"]
    changed = {"name": "Яблоко Гала", "description": None, "price": "99.50", "quantity": 10}

    response = client.put(f"/products/{product_id}", json=changed)

    assert response.status_code == 200
    stored = client.get(f"/products/{product_id}").json()
    assert response.json() == stored
    assert stored["id"] == product_id
    assert stored["name"] == "Яблоко Гала"
    assert stored["description"] is None
    assert Decimal(stored["price"]) == Decimal("99.50")
    assert stored["quantity"] == 10


def test_update_missing_product_returns_404(client):
    assert client.put("/products/42", json=APPLE).status_code == 404
    assert client.get("/products").json() == []


def test_update_product_rejects_invalid_payload(client):
    created = client.post("/products", json=APPLE).json()

    response = client.put(f"/products/{created['id']}", json={**APPLE, "price": "-1"})

    assert response.status_code == 422
    assert client.get(f"/products/{created['id']}").json() == created


def test_list_products(client):
    assert client.get("/products").json() == []

    first = client.post("/products", json=APPLE).json()
    second = client.post("/products", json={"name": "Манго", "price": "350"}).json()

    response = client.get("/products")

    assert response.status_code == 200
    assert response.json() == [first, second]


def test_products_survive_restart(tmp_path):
    db_path = str(tmp_path / "test.db")
    created = TestClient(create_app(db_path)).post("/products", json=APPLE).json()

    assert TestClient(create_app(db_path)).get("/products").json() == [created]
