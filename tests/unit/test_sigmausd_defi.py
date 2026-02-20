from unittest.mock import MagicMock, patch

import pytest

from ergo_agent.defi.sigmausd import SigmaUSD


class MockNode:
    node_url = "http://mock"

    def get_height(self):
        return 1000000

    def get_box_by_id(self, box_id):
        return None

    def get_unspent_boxes(self, address):
        mock_box = MagicMock()
        mock_box.box_id = "test_wallet_box"
        mock_box.value = 1000 * 10**9 # 1000 ERG
        mock_box.tokens = []
        return [mock_box]

    def _resolve_address_to_tree(self, addr):
        return "1001040"

class MockWallet:
    @property
    def address(self):
        # Must be a valid base58 P2PK address for the offline ErgoTree rust builder
        return "9g16ZzCEg5P3oMhwU564i585BDBK6m36H7UuW25LDEw4n5oYw5H"

@pytest.fixture
def sigmausd_client():
    node = MockNode()
    return SigmaUSD(node=node)

@pytest.fixture
def mock_wallet():
    return MockWallet()

@patch('ergo_agent.defi.sigmausd.SigmaUSD.get_bank_state')
def test_mint_sigusd_success(mock_get_state, sigmausd_client, mock_wallet):
    # Mock a healthy bank state
    mock_get_state.return_value = {
        "reserve_ratio_percent": 500, # > 400% so we can mint SigUSD
        "sigusd_price_nanoerg": 20_000_000,
    }

    # Try to mint 100 SigUSD ($1.00)
    with patch('ergo_agent.core.builder.TransactionBuilder._resolve_ergo_tree', return_value="1001040"):
        tx = sigmausd_client.build_mint_sigusd_tx(100, mock_wallet)

    assert tx is not None
    assert "outputs" in tx
    assert len(tx["outputs"]) >= 3 # proxy output, fee, change

    # 100 * 20m = 2_000_000_000. Protocol fee 2% is 40_000_000. Total = 2_040_000_000 + Dust
    proxy_output = tx["outputs"][0]
    assert proxy_output["value"] == 2_040_000_000 + 1_000_000

@patch('ergo_agent.defi.sigmausd.SigmaUSD.get_bank_state')
def test_mint_sigusd_fails_low_ratio(mock_get_state, sigmausd_client, mock_wallet):
    # Mock a low ratio where minting SigUSD is forbidden
    mock_get_state.return_value = {
        "reserve_ratio_percent": 350, # < 400%
        "sigusd_price_nanoerg": 20_000_000,
    }

    with pytest.raises(Exception, match="below the 400% minimum threshold"):
        sigmausd_client.build_mint_sigusd_tx(100, mock_wallet)

@patch('ergo_agent.defi.sigmausd.SigmaUSD.get_bank_state')
def test_redeem_sigrsv_fails_low_ratio(mock_get_state, sigmausd_client, mock_wallet):
    # Mock a low ratio where redeeming SigRSV is forbidden (causes bank insolvency)
    mock_get_state.return_value = {
        "reserve_ratio_percent": 399,
        "sigrsv_price_nanoerg": 10000,
    }

    with pytest.raises(Exception, match="below the 400% minimum threshold for Reserve redemption"):
        sigmausd_client.build_redeem_sigrsv_tx(100, mock_wallet)
