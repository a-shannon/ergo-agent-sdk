"""
Integration tests for ergo_agent.core.node (ErgoNode client).

These tests run against the live Ergo Explorer API.

Run:  pytest tests/integration/ -v -m integration
"""

import pytest

from ergo_agent.core.node import ErgoNode


@pytest.fixture(scope="module")
def node():
    """Node with generous timeout for API calls to heavy addresses."""
    n = ErgoNode(timeout=30.0)
    yield n
    n.close()


@pytest.fixture(scope="module")
def miner_address():
    """Fetch a real miner address from the latest block."""
    import httpx

    r = httpx.get(
        "https://api.ergoplatform.com/api/v1/blocks?limit=1",
        timeout=15.0,
    )
    return r.json()["items"][0]["miner"]["address"]


@pytest.mark.integration
class TestErgoNode:
    """Test ErgoNode methods against the live Ergo network."""

    def test_get_height(self, node):
        height = node.get_height()
        assert isinstance(height, int)
        assert height > 1_700_000, f"Height {height} seems too low"

    def test_get_network_info(self, node):
        info = node.get_network_info()
        assert "height" in info
        assert "lastBlockId" in info
        assert isinstance(info["height"], int)

    def test_get_balance_real_address(self, node, miner_address):
        """Get balance for a miner address (always has boxes)."""
        try:
            balance = node.get_balance(miner_address)
            assert balance.erg >= 0.0
            assert isinstance(balance.tokens, list)
        except Exception as e:
            if "timeout" in str(e).lower() or "ReadTimeout" in str(type(e).__name__):
                pytest.skip(f"API timeout for miner address (expected for heavy addresses): {e}")
            raise

    def test_get_unspent_boxes(self, node, miner_address):
        """Fetch unspent boxes for a known-active address."""
        try:
            boxes = node.get_unspent_boxes(miner_address)
            assert isinstance(boxes, list)
            if len(boxes) > 0:
                box = boxes[0]
                assert hasattr(box, "box_id")
                assert hasattr(box, "value")
                assert box.value > 0
        except Exception as e:
            if "timeout" in str(e).lower() or "ReadTimeout" in str(type(e).__name__):
                pytest.skip(f"API timeout (expected for heavy addresses): {e}")
            raise

    def test_get_mempool_transactions(self, node, miner_address):
        """Mempool may be empty but should return a list."""
        txs = node.get_mempool_transactions(miner_address)
        assert isinstance(txs, list)

    def test_get_oracle_pool_box(self, node):
        """Fetch the ERG/USD oracle pool box."""
        oracle_nft = "011d3364de07e5a26f0c4eef0852cddb387039a921b7154ef3cab22c6eda887f"
        box = node.get_oracle_pool_box(oracle_nft)
        assert box is not None
        assert box.box_id is not None
        assert box.value > 0


@pytest.mark.integration
class TestErgoNodeTransactionHistory:
    """Test transaction history retrieval."""

    def test_get_transaction_history(self, node, miner_address):
        try:
            txs = node.get_transaction_history(miner_address, limit=5)
            assert isinstance(txs, list)
            assert len(txs) <= 5
        except Exception as e:
            if "timeout" in str(e).lower() or "ReadTimeout" in str(type(e).__name__):
                pytest.skip(f"API timeout for tx history (expected for heavy addresses): {e}")
            raise
