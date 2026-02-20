from unittest.mock import MagicMock, patch

import pytest

from ergo_agent.defi.treasury import ErgoTreasury


class MockNode:
    node_url = "http://mock"
    def get_height(self): return 1000000
    def get_box_by_id(self, box_id): return None
    def get_unspent_boxes(self, address):
        mock_box = MagicMock()
        mock_box.box_id = "test_wallet_box"
        mock_box.value = 1000 * 10**9 # 1000 ERG
        mock_box.tokens = []
        return [mock_box]

    def _resolve_address_to_tree(self, addr):
        return "1001040..."

class MockWallet:
    @property
    def address(self):
        return "9fTestWalletAddress123456"

@pytest.fixture
def treasury_client():
    node = MockNode()
    return ErgoTreasury(node=node)

@pytest.fixture
def mock_wallet():
    return MockWallet()

def test_build_proposal_tx_success(treasury_client, mock_wallet):
    with patch('ergo_agent.core.builder.TransactionBuilder._resolve_ergo_tree', return_value="1001040"):
        tx = treasury_client.build_proposal_tx(
            treasury_address="4MQyMKvMbsfPeEpKbgXm9E",
            target_address="9fTestTargetAddress",
            amount_erg=50.0,
            description="Fund the developers",
            wallet=mock_wallet
        )

    assert tx is not None
    assert "outputs" in tx

    # Verify the proposal output
    proposal_output = tx["outputs"][0]
    assert proposal_output["value"] == 10_000_000 # 0.01 ERG

    regs = proposal_output["additionalRegisters"]
    assert "R4" in regs
    assert "R5" in regs
    assert "R6" in regs

def test_build_vote_tx_unimplemented(treasury_client, mock_wallet):
    with pytest.raises(NotImplementedError):
        treasury_client.build_vote_tx("box_id", True, mock_wallet)

def test_build_execute_tx_unimplemented(treasury_client, mock_wallet):
    with pytest.raises(NotImplementedError):
        treasury_client.build_execute_tx("box_id", "treasury_addr", mock_wallet)
