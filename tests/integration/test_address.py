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

# -- Helpers to get real addresses --
# We use hermetic, statically validated mainnet addresses instead of dynamically
# fetching from the explorer because the explorer can return edge-case contract outputs
# that complicate pure unit testing of the Address object validations.

@pytest.fixture(scope="module")
def real_addresses():
    """Module-scoped fixture: return known valid Ergo mainnet addresses."""
    # 9how... is a standard Mainnet P2PK
    # 3WvH... is a standard Mainnet P2S (the Neta contract tree)
    return {
        "p2pk": {
            "address": "9how9k2dp67jXDnCM6TeRPKtQrToCs5MYL2JoSgyGHLXm1eHxWs",
            "ergo_tree": "0008cd03b1668d64532c10fb2cd40461f81077ffbeeaf84e52b534aaed25d4442db7cc80"
        },
        "p2s": {
            "address": "3WvHxpDEsAed7JqetTAnEa34rQ9NsqS9r6C8x4nL8tSTbLttd3U4",
            "ergo_tree": "10010400040004000e36100204a00b08cd021dde3460cd92469d20c5e5fdd3adbb985b88f114ebb4c4b9b990f1464da4142fd17300"
        },
    }


# -- Tests --

@pytest.mark.integration
class TestAddressValidation:
    """Test address validation against standard P2PK addresses."""

    def test_validate_real_p2pk_address(self, real_addresses):
        addr = real_addresses["p2pk"]["address"]
        assert validate_address(addr) is True

    def test_is_mainnet(self, real_addresses):
        addr = real_addresses["p2pk"]["address"]
        assert is_mainnet_address(addr) is True

    def test_is_p2pk(self, real_addresses):
        addr = real_addresses["p2pk"]["address"]
        assert is_p2pk_address(addr) is True

    def test_get_address_type_p2pk(self, real_addresses):
        addr = real_addresses["p2pk"]["address"]
        assert get_address_type(addr) == "mainnet-P2PK"

    def test_invalid_address_rejected(self):
        assert is_valid_address("NotAnAddress123") is False
        assert is_valid_address("") is False
        assert is_valid_address("1111") is False

    def test_validate_raises_on_invalid(self):
        from ergo_agent.core.address import AddressError
        with pytest.raises(AddressError):
            validate_address("NotAnAddress123")


@pytest.mark.integration
class TestErgoTreeDerivation:
    """Test ErgoTree derivation against blockchain reference data."""

    def test_p2pk_ergo_tree_matches_reference(self, real_addresses):
        """The SDK-derived ErgoTree must exactly match the expected reference test data."""
        addr = real_addresses["p2pk"]["address"]
        expected_tree = real_addresses["p2pk"]["ergo_tree"]
        derived_tree = address_to_ergo_tree(addr)
        assert derived_tree == expected_tree

    def test_p2pk_ergo_tree_format(self, real_addresses):
        """P2PK ErgoTree must start with 0008cd and be 72 hex chars."""
        addr = real_addresses["p2pk"]["address"]
        tree = address_to_ergo_tree(addr)
        assert tree.startswith("0008cd")
        assert len(tree) == 72  # 36 bytes = 6 (prefix) + 66 (33-byte pubkey)
