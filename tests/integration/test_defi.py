"""
Integration tests for ergo_agent.defi (OracleReader, SpectrumDEX).

These tests run against live APIs.

Run:  pytest tests/integration/ -v -m integration
"""

import pytest

from ergo_agent.core.node import ErgoNode
from ergo_agent.defi.oracle import OracleReader
from ergo_agent.defi.spectrum import SpectrumDEX


@pytest.fixture(scope="module")
def node():
    n = ErgoNode(timeout=30.0)
    yield n
    n.close()


# -- Oracle Pool v2 --


@pytest.mark.integration
class TestOracleReader:
    """Test OracleReader against the live Oracle Pool v2."""

    def test_get_erg_usd_price(self, node):
        oracle = OracleReader(node)
        price = oracle.get_erg_usd_price()
        assert isinstance(price, float)
        assert 0.01 < price < 100.0, f"ERG/USD price {price} seems unreasonable"

    def test_get_oracle_box_id(self, node):
        oracle = OracleReader(node)
        box_id = oracle.get_oracle_box_id()
        assert isinstance(box_id, str)
        assert len(box_id) == 64, f"Box ID length {len(box_id)} != 64"


# -- Spectrum DEX --


@pytest.mark.integration
class TestSpectrumDEX:
    """Test SpectrumDEX against the live Spectrum Finance API."""

    def test_get_pools(self, node):
        dex = SpectrumDEX(node)
        try:
            markets = dex.get_pools()
            assert isinstance(markets, list)
            assert len(markets) > 0, "Spectrum should have at least one active market"

            # Check market structure
            m = markets[0]
            assert m.base_id is not None
            assert m.quote_id is not None
            assert m.base_symbol is not None
        finally:
            dex.close()

    def test_get_erg_price_in_sigusd(self, node):
        dex = SpectrumDEX(node)
        try:
            price = dex.get_erg_price_in_sigusd()
            assert isinstance(price, float)
            assert 0.01 < price < 100.0, f"ERG price ${price} seems unreasonable"
        finally:
            dex.close()

    def test_get_quote_erg_to_sigusd(self, node):
        dex = SpectrumDEX(node)
        try:
            quote = dex.get_quote(
                token_in="ERG",
                token_out="SigUSD",
                amount_erg=1.0,
            )
            assert quote is not None
            assert quote.token_out_amount > 0
            assert quote.fee_pct >= 0
        finally:
            dex.close()

    def test_get_quote_small_amount(self, node):
        """Verify quote works for small amounts without crashing."""
        dex = SpectrumDEX(node)
        try:
            quote = dex.get_quote(
                token_in="ERG",
                token_out="SigUSD",
                amount_erg=0.01,
            )
            assert quote is not None
            assert quote.token_out_amount >= 0
        finally:
            dex.close()

    def test_build_swap_order(self, node):
        """Test swap order construction (does NOT submit to chain)."""
        import httpx

        dex = SpectrumDEX(node)
        try:
            # Get a real P2PK address
            r = httpx.get(
                "https://api.ergoplatform.com/api/v1/blocks?limit=1",
                timeout=15.0,
            )
            block_id = r.json()["items"][0]["id"]
            r2 = httpx.get(
                f"https://api.ergoplatform.com/api/v1/blocks/{block_id}",
                timeout=15.0,
            )
            block = r2.json()
            txs = block["block"]["blockTransactions"]
            return_addr = None
            for tx in txs:
                for out in tx["outputs"]:
                    if out.get("ergoTree", "").startswith("0008cd"):
                        return_addr = out["address"]
                        break
                if return_addr:
                    break

            if return_addr is None:
                pytest.skip("No P2PK address found in latest block")

            order = dex.build_swap_order(
                token_in="ERG",
                token_out="SigUSD",
                amount_erg=1.0,
                return_address=return_addr,
                max_slippage_pct=3.0,
            )

            assert "ergo_tree" in order
            assert "value_nanoerg" in order
            assert "registers" in order
            assert "quote" in order
            assert order["value_nanoerg"] > 0
            assert "R4" in order["registers"]
            assert "R5" in order["registers"]
        finally:
            dex.close()
