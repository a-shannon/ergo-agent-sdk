import pytest
from unittest.mock import MagicMock, patch
from ergo_agent.defi.rosen import RosenBridge
from ergo_agent.core.builder import TransactionBuilderError

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
def rosen_client():
    node = MockNode()
    client = RosenBridge(node=node)
    return client

@pytest.fixture
def mock_wallet():
    return MockWallet()

def test_build_bridge_tx_success(rosen_client, mock_wallet):
    with patch('ergo_agent.core.builder.TransactionBuilder._resolve_ergo_tree', return_value="1001040"):
        tx = rosen_client.build_bridge_tx("Cardano", "addr1qxyz...", 10.0, {}, mock_wallet)
    
    assert tx is not None
    assert "outputs" in tx
    
    # Verify the Rosen watcher output
    bridge_output = tx["outputs"][0]
    # 10 ERG base + 0.02 bridge fee + 0.002 network fee
    assert bridge_output["value"] == 10_022_000_000
    
    # Verify R4 and R5 registers contain the destination data
    assert bridge_output["additionalRegisters"]["R4"] == "0e0743617264616e6f" # "Cardano" in hex
    assert bridge_output["additionalRegisters"]["R5"] == "0e0c61646472317178797a2e2e2e" # "addr1qxyz..." in hex

def test_build_bridge_tx_invalid_chain(rosen_client, mock_wallet):
    with pytest.raises(Exception, match="Unsupported destination chain"):
        rosen_client.build_bridge_tx("Solana", "addr...", 10.0, {}, mock_wallet)
