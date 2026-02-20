import pytest

from ergo_agent.defi.sigmausd import SigmaUSD


@pytest.fixture
def sigmausd_client():
    return SigmaUSD()

def test_get_bank_state(sigmausd_client):
    """Test that we can retrieve the SigmaUSD bank state from TokenJay."""
    state = sigmausd_client.get_bank_state()

    assert "reserve_ratio_percent" in state
    assert "sigusd_price_nanoerg" in state
    assert "sigusd_price_erg" in state
    assert "sigrsv_price_nanoerg" in state
    assert "sigrsv_price_erg" in state
    assert "status" in state

    assert state["reserve_ratio_percent"] > 0
    assert state["sigusd_price_nanoerg"] > 0

    # State should be either Healthy or Warning
    assert state["status"] in ["Healthy", "Warning (Minting restricted)"]
