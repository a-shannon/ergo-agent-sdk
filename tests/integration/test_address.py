"""
Integration tests for ergo_agent.core.address module.

These tests validate address operations against real Ergo blockchain data.
They require network access to the Ergo Explorer API.

Run:  pytest tests/integration/ -v -m integration
"""

import pytest

from ergo_agent.core.address import (
    AddressError,
    address_to_ergo_tree,
    get_address_type,
    is_mainnet_address,
    is_p2pk_address,
    is_valid_address,
    validate_address,
)

# -- Helpers to get real addresses from the blockchain --

_EXPLORER = "https://api.ergoplatform.com"


def _get_real_addresses():
    """Fetch real P2PK and P2S addresses from a recent block."""
    import httpx

    client = httpx.Client(timeout=15)
    try:
        resp = client.get(f"{_EXPLORER}/api/v1/blocks?limit=1")
        block_id = resp.json()["items"][0]["id"]
        resp2 = client.get(f"{_EXPLORER}/api/v1/blocks/{block_id}")
        block = resp2.json()
        txs = block["block"]["blockTransactions"]

        p2pk_addr, p2pk_tree = None, None
        p2s_addr, p2s_tree = None, None

        for tx in txs:
            for out in tx["outputs"]:
                tree = out.get("ergoTree", "")
                addr = out.get("address", "")
                if tree.startswith("0008cd") and p2pk_addr is None:
                    p2pk_addr, p2pk_tree = addr, tree
                elif not tree.startswith("0008cd") and p2s_addr is None:
                    p2s_addr, p2s_tree = addr, tree
                if p2pk_addr and p2s_addr:
                    break
            if p2pk_addr and p2s_addr:
                break

        return {
            "p2pk": {"address": p2pk_addr, "ergo_tree": p2pk_tree},
            "p2s": {"address": p2s_addr, "ergo_tree": p2s_tree},
        }
    finally:
        client.close()


@pytest.fixture(scope="module")
def real_addresses():
    """Module-scoped fixture: fetch real addresses once for all tests."""
    return _get_real_addresses()


# -- Tests --


@pytest.mark.integration
class TestAddressValidation:
    """Test address validation against real blockchain addresses."""

    def test_validate_real_p2pk_address(self, real_addresses):
        addr = real_addresses["p2pk"]["address"]
        if addr is None:
            pytest.skip("No P2PK address found in latest block")
        assert validate_address(addr) is True

    def test_validate_real_p2s_address(self, real_addresses):
        addr = real_addresses["p2s"]["address"]
        if addr is None:
            pytest.skip("No P2S address found in latest block")
        assert validate_address(addr) is True

    def test_is_mainnet(self, real_addresses):
        addr = real_addresses["p2pk"]["address"]
        if addr is None:
            pytest.skip("No P2PK address found")
        assert is_mainnet_address(addr) is True

    def test_is_p2pk(self, real_addresses):
        addr = real_addresses["p2pk"]["address"]
        if addr is None:
            pytest.skip("No P2PK address found")
        assert is_p2pk_address(addr) is True

    def test_p2s_is_not_p2pk(self, real_addresses):
        addr = real_addresses["p2s"]["address"]
        if addr is None:
            pytest.skip("No P2S address found")
        assert is_p2pk_address(addr) is False

    def test_get_address_type_p2pk(self, real_addresses):
        addr = real_addresses["p2pk"]["address"]
        if addr is None:
            pytest.skip("No P2PK address found")
        assert get_address_type(addr) == "mainnet-P2PK"

    def test_invalid_address_rejected(self):
        assert is_valid_address("NotAnAddress123") is False
        assert is_valid_address("") is False
        assert is_valid_address("1111") is False

    def test_validate_raises_on_invalid(self):
        with pytest.raises(AddressError):
            validate_address("NotAnAddress123")


@pytest.mark.integration
class TestErgoTreeDerivation:
    """Test ErgoTree derivation against blockchain reference data."""

    def test_p2pk_ergo_tree_matches_explorer(self, real_addresses):
        """The SDK-derived ErgoTree must exactly match what the Explorer reports."""
        addr = real_addresses["p2pk"]["address"]
        expected_tree = real_addresses["p2pk"]["ergo_tree"]
        if addr is None or expected_tree is None:
            pytest.skip("No P2PK address found")

        derived_tree = address_to_ergo_tree(addr)
        assert derived_tree == expected_tree, (
            f"ErgoTree mismatch:\n"
            f"  Derived:  {derived_tree[:60]}...\n"
            f"  Explorer: {expected_tree[:60]}..."
        )

    def test_p2pk_ergo_tree_format(self, real_addresses):
        """P2PK ErgoTree must start with 0008cd and be 72 hex chars."""
        addr = real_addresses["p2pk"]["address"]
        if addr is None:
            pytest.skip("No P2PK address found")

        tree = address_to_ergo_tree(addr)
        assert tree.startswith("0008cd")
        assert len(tree) == 72  # 36 bytes = 6 (prefix) + 66 (33-byte pubkey)
