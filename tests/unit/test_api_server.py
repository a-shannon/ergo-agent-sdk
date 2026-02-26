import pytest
from fastapi.testclient import TestClient

from ergo_agent.api.server import app
from ergo_agent.api.models import DepositRequest, WithdrawRequest


@pytest.fixture
def client():
    # We won't test full signature chains in this simple unit test
    # Just asserting the API parses inputs and returns validation errors appropriately for bad inputs
    # To truly test e2e, we need the node available
    with TestClient(app) as c:
        yield c


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_deposit_missing_pool(client):
    # Should fail pydantic validation
    response = client.post("/pool/deposit", json={"denomination": 1000})
    assert response.status_code == 422


def test_withdraw_missing_secret(client):
    response = client.post(
        "/pool/withdraw", 
        json={"recipient_address": "9ew...", "pool_box_id": "abc"}
    )
    assert response.status_code == 422


def test_withdraw_missing_pool(client):
    response = client.post(
        "/pool/withdraw", 
        json={
            "recipient_address": "9ew...", 
            "secret_key": "01"*32
        }
    )
    # The route requires pool_box_id right now
    assert response.status_code == 400
    assert "pool_box_id is currently required" in response.text
