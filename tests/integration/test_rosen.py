import pytest
from ergo_agent.defi.rosen import RosenBridge

@pytest.fixture
def rosen_client():
    return RosenBridge()

def test_get_bridge_status(rosen_client):
    """Test that we can retrieve the Rosen Bridge status from DefiLlama."""
    state = rosen_client.get_bridge_status()
    
    assert "name" in state
    assert state["name"] == "Rosen Bridge"
    assert "global_tvl_usd" in state
    assert state["global_tvl_usd"] > 0
    assert "supported_chains" in state
    assert "Cardano" in state["supported_chains"]
    assert "chain_tvls_usd" in state
    assert "Cardano" in state["chain_tvls_usd"]
