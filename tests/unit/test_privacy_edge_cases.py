"""
Phase 4: Edge case unit tests for privacy pool protocol.
All node/wallet calls are mocked — no network required.

Tests cover:
- Invalid secret key handling (zero, too short, non-hex)
- Pool capacity enforcement
- Exact denomination enforcement (v6: no 99% fee)
- Concurrent transaction building
- Empty pool withdrawal guard
"""

from unittest.mock import MagicMock

import pytest

from ergo_agent.core.models import Box, Token
from ergo_agent.core.privacy import compute_key_image, generate_fresh_secret
from ergo_agent.defi.privacy_pool import PoolValidationError, PrivacyPoolClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EMPTY_AVL_TREE = "64befb05d26d04d4d4d1dc877f1ea2f879509a17191e5bd6e60ca98d3e3609a92500072100"
TOKEN_ID = "db60c1a42fa4d7da0b6dac60ffa862c1f45560ee5da7dbbae471aafe924c496f"


def make_pool_box(
    box_id="abc123",
    value=1_000_000,
    ergo_tree="0008cd02deadbeef",
    token_amount=5000,
    r4="1302" + ("02" + "aa" * 32) + ("02" + "bb" * 32),  # 2 depositors
    r5=EMPTY_AVL_TREE,
    r6="05c801",  # denom = 100
    r7="0420",    # maxRing = 16
):
    box = Box(
        box_id=box_id,
        value=value,
        ergo_tree=ergo_tree,
        creation_height=1_200_000,
        additional_registers={"R4": r4, "R5": r5, "R6": r6, "R7": r7},
    )
    box.tokens = [Token(token_id=TOKEN_ID, amount=token_amount, name="TEST", decimals=0)]
    return box


def make_client():
    node = MagicMock()
    wallet = MagicMock()
    wallet.address = "3WxTestAddress"
    client = PrivacyPoolClient.__new__(PrivacyPoolClient)
    client.node = node
    client.wallet = wallet
    client.MOCK_CASH_V3_POOL_ERGO_TREE = "0008cd02deadbeef"
    client.pool_address = "3WxPoolAddress"
    return client, node


# ---------------------------------------------------------------------------
# Key Image Computation Edge Cases
# ---------------------------------------------------------------------------

class TestKeyImageEdgeCases:
    """Test compute_key_image with pathological inputs."""

    def test_valid_secret_produces_valid_key_image(self):
        """A valid 32-byte secret should produce a valid 66-char compressed point."""
        secret, pubkey = generate_fresh_secret()
        key_image = compute_key_image(secret)
        assert len(key_image) == 66
        assert key_image[:2] in ("02", "03")

    def test_zero_secret_raises_value_error(self):
        """Zero scalar produces identity point — must raise ValueError."""
        with pytest.raises(ValueError, match="zero"):
            compute_key_image("00" * 32)

    def test_too_short_secret_raises(self):
        """Secret shorter than 64 hex chars should raise ValueError."""
        with pytest.raises(ValueError, match="64 hex"):
            compute_key_image("abcd")  # Only 2 bytes

    def test_non_hex_secret_raises(self):
        """Non-hex string should raise ValueError."""
        with pytest.raises(ValueError):
            compute_key_image("zz" * 32)

    def test_oversized_secret_raises(self):
        """Secret larger than the curve order should raise ValueError."""
        huge_secret = "ff" * 32
        with pytest.raises(ValueError, match="curve order"):
            compute_key_image(huge_secret)


# ---------------------------------------------------------------------------
# Withdrawal Edge Cases
# ---------------------------------------------------------------------------

class TestWithdrawalEdgeCases:
    """Test build_withdrawal_tx with edge case inputs."""

    def test_withdrawal_exact_denomination(self, monkeypatch):
        """V6: Note output must be exact denomination, never 99%."""
        import ergo_agent.core.address as addr_mod
        monkeypatch.setattr(addr_mod, "address_to_ergo_tree", lambda *a, **kw: "0008cd03recipient")

        client, node = make_client()
        # denom=100 (R6 "05c801"), pool has 5000 tokens
        pool_box = make_pool_box()
        node.get_box_by_id.return_value = pool_box

        secret = "ab" * 32
        builder = client.build_withdrawal_tx("abc123", "3WxRecipient", secret)

        note_out = builder._outputs[1]
        denom = client._decode_r6_denomination("05c801")
        assert note_out["tokens"][0]["amount"] == denom  # Exact, not 99%

    def test_withdrawal_pool_not_found(self):
        """Must raise ValueError if pool box doesn't exist."""
        client, node = make_client()
        node.get_box_by_id.return_value = None

        with pytest.raises(ValueError, match="not found"):
            client.build_withdrawal_tx("nonexistent", "3WxRecipient", "aa" * 32)

    def test_withdrawal_pool_tokens_decrease_by_denom(self, monkeypatch):
        """Pool output tokens must decrease by exactly one denomination."""
        import ergo_agent.core.address as addr_mod
        monkeypatch.setattr(addr_mod, "address_to_ergo_tree", lambda *a, **kw: "0008cd03recipient")

        client, node = make_client()
        pool_box = make_pool_box(token_amount=3000, r6="05d00f")  # denom=1000
        node.get_box_by_id.return_value = pool_box

        secret = "cc" * 32
        builder = client.build_withdrawal_tx("abc123", "3WxRecipient", secret)

        pool_out = builder._outputs[0]
        denom = client._decode_r6_denomination("05d00f")
        assert pool_out["tokens"][0]["amount"] == 3000 - denom

    def test_withdrawal_r5_is_avltree_format(self, monkeypatch):
        """After withdrawal, new R5 must be AvlTree format (starts with 0x64)."""
        import ergo_agent.core.address as addr_mod
        monkeypatch.setattr(addr_mod, "address_to_ergo_tree", lambda *a, **kw: "0008cd03recipient")

        client, node = make_client()
        pool_box = make_pool_box()
        node.get_box_by_id.return_value = pool_box

        secret = "dd" * 32
        builder = client.build_withdrawal_tx("abc123", "3WxRecipient", secret)

        new_r5 = builder._outputs[0]["registers"]["R5"]
        assert new_r5.startswith("64"), f"Expected AvlTree format (0x64), got {new_r5[:4]}"


# ---------------------------------------------------------------------------
# Deposit Edge Cases
# ---------------------------------------------------------------------------

class TestDepositEdgeCases:
    """Test deposit transaction edge cases."""

    def test_deposit_pool_at_capacity(self):
        """Deposit to a full pool (ring_size == maxRing) must be rejected."""
        client, node = make_client()
        # Create pool with maxRing=2 and already 2 keys
        pool_box = make_pool_box(
            r4="1302" + ("02" + "aa" * 32) + ("02" + "bb" * 32),
            r7="0404",  # maxRing = 2
        )
        node.get_box_by_id.return_value = pool_box

        new_key = "02" + "cc" * 32
        with pytest.raises((PoolValidationError, ValueError)):
            client.build_deposit_tx("abc123", new_key, 100)

    def test_deposit_duplicate_key_rejected(self):
        """Depositing a key already in R4 must be rejected."""
        client, node = make_client()
        pool_box = make_pool_box()
        node.get_box_by_id.return_value = pool_box

        # Try to deposit the same key as the first depositor
        existing_key = "02" + "aa" * 32
        with pytest.raises(PoolValidationError, match="already exists"):
            client.build_deposit_tx("abc123", existing_key, 100)


# ---------------------------------------------------------------------------
# Concurrent Transaction Building
# ---------------------------------------------------------------------------

class TestConcurrentBuilds:
    """Test that concurrent builds against the same pool UTXO both succeed."""

    def test_two_withdrawals_same_utxo_both_build(self, monkeypatch):
        """Two withdrawal builders against the same pool box should both
        produce valid unsigned TXs. Contention happens at submit only."""
        import ergo_agent.core.address as addr_mod
        monkeypatch.setattr(addr_mod, "address_to_ergo_tree", lambda *a, **kw: "0008cd03recipient")

        client, node = make_client()
        pool_box = make_pool_box()
        node.get_box_by_id.return_value = pool_box

        secret1 = "e1" * 32
        secret2 = "e2" * 32

        builder1 = client.build_withdrawal_tx("abc123", "3WxAddr1", secret1)
        builder2 = client.build_withdrawal_tx("abc123", "3WxAddr2", secret2)

        assert len(builder1._outputs) == 2
        assert len(builder2._outputs) == 2

    def test_deposit_and_withdrawal_same_utxo(self, monkeypatch):
        """A deposit and withdrawal against the same UTXO both build OK."""
        import ergo_agent.core.address as addr_mod
        monkeypatch.setattr(addr_mod, "address_to_ergo_tree", lambda *a, **kw: "0008cd03recipient")

        client, node = make_client()
        pool_box = make_pool_box()
        node.get_box_by_id.return_value = pool_box

        dep_key = "02" + "f1" * 32
        builder_dep = client.build_deposit_tx("abc123", dep_key, 100)

        wit_secret = "f2" * 32
        builder_wit = client.build_withdrawal_tx("abc123", "3WxRecipient", wit_secret)

        assert len(builder_dep._outputs) >= 1
        assert len(builder_wit._outputs) >= 1


# ---------------------------------------------------------------------------
# Fresh Secret Generation
# ---------------------------------------------------------------------------

class TestFreshSecretGeneration:
    """Test generate_fresh_secret() produces valid, unique keypairs."""

    def test_generates_valid_keypair(self):
        secret, pubkey = generate_fresh_secret()
        assert len(secret) == 64  # 32 bytes hex
        assert len(pubkey) == 66  # 33 bytes hex
        assert pubkey[:2] in ("02", "03")

    def test_generates_unique_keys(self):
        """Two calls should produce different keys (probabilistically)."""
        s1, p1 = generate_fresh_secret()
        s2, p2 = generate_fresh_secret()
        assert s1 != s2
        assert p1 != p2

    def test_secret_computes_correct_key_image(self):
        """Key image from a fresh secret should be a valid compressed point."""
        secret, pubkey = generate_fresh_secret()
        ki = compute_key_image(secret)
        assert len(ki) == 66
        assert ki[:2] in ("02", "03")
        # Key image should NOT equal the public key
        assert ki != pubkey
