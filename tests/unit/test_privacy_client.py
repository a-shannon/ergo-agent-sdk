"""
Unit tests for ergo_agent.defi.privacy_client — User-Facing Privacy Client.
"""

import secrets

import pytest

from ergo_agent.crypto.pedersen import (
    SECP256K1_N,
    PedersenCommitment,
)
from ergo_agent.defi.privacy_client import (
    DepositSecret,
    PrivacyPoolClient,
)
from ergo_agent.relayer.pool_deployer import (
    NANOERG,
)


def _random_r() -> int:
    return secrets.randbelow(SECP256K1_N - 1) + 1


MOCK_ERGO_TREE = "0008cd02" + "aa" * 32


# ==============================================================================
# Deposit Operations
# ==============================================================================


class TestCreateDeposit:
    """Tests for deposit secret generation."""

    def test_1_erg_deposit(self):
        client = PrivacyPoolClient()
        secret = client.create_deposit("1_erg")
        assert secret.amount == 1 * NANOERG
        assert secret.tier == "1_erg"
        assert len(secret.commitment_hex) == 66

    def test_10_erg_deposit(self):
        client = PrivacyPoolClient()
        secret = client.create_deposit("10_erg")
        assert secret.amount == 10 * NANOERG

    def test_100_erg_deposit(self):
        client = PrivacyPoolClient()
        secret = client.create_deposit("100_erg")
        assert secret.amount == 100 * NANOERG

    def test_unknown_tier_rejected(self):
        client = PrivacyPoolClient()
        with pytest.raises(ValueError, match="Unknown tier"):
            client.create_deposit("1000_erg")

    def test_commitment_is_valid(self):
        client = PrivacyPoolClient()
        secret = client.create_deposit("10_erg")
        assert PedersenCommitment.verify(
            secret.commitment_hex, secret.blinding_factor, secret.amount
        )

    def test_each_deposit_unique(self):
        client = PrivacyPoolClient()
        s1 = client.create_deposit("10_erg")
        s2 = client.create_deposit("10_erg")
        assert s1.commitment_hex != s2.commitment_hex
        assert s1.blinding_factor != s2.blinding_factor


class TestBuildDepositIntent:
    """Tests for deposit intent box construction."""

    def test_basic_intent(self):
        client = PrivacyPoolClient()
        secret = client.create_deposit("10_erg")
        intent = client.build_deposit_intent(secret, MOCK_ERGO_TREE)

        assert intent["meta"]["type"] == "IntentToDeposit"
        assert intent["meta"]["tier"] == "10_erg"
        assert intent["value"] > secret.amount  # denom + min value
        assert "R4" in intent["registers"]
        assert "R5" in intent["registers"]

    def test_commitment_in_r4(self):
        client = PrivacyPoolClient()
        secret = client.create_deposit("1_erg")
        intent = client.build_deposit_intent(secret, MOCK_ERGO_TREE)

        # R4 should contain the commitment as GroupElement (07 prefix)
        assert intent["registers"]["R4"].startswith("07")
        assert secret.commitment_hex in intent["registers"]["R4"]


# ==============================================================================
# Withdrawal Operations
# ==============================================================================


class TestBuildWithdrawalProof:
    """Tests for withdrawal proof construction."""

    def test_basic_withdrawal(self):
        client = PrivacyPoolClient()
        secret = client.create_deposit("10_erg")
        decoys = [PedersenCommitment.commit(_random_r(), 10 * NANOERG) for _ in range(3)]
        payout = "0008cd02" + "bb" * 32

        proof = client.build_withdrawal_proof(secret, decoys, payout)

        assert len(proof.nullifier_hex) == 66
        assert proof.secondary_gen_hex is None  # v9: U=H hardcoded, not per-withdrawal
        assert proof.payout_ergo_tree == payout
        assert proof.ring_size == 4  # 3 decoys + 1 real

    def test_ring_data_complete(self):
        client = PrivacyPoolClient()
        secret = client.create_deposit("1_erg")
        decoys = [PedersenCommitment.commit(_random_r(), 1 * NANOERG) for _ in range(5)]

        proof = client.build_withdrawal_proof(secret, decoys, MOCK_ERGO_TREE)

        assert "real_index" in proof.ring_data
        assert "commitments" in proof.ring_data
        assert "nullifier" in proof.ring_data
        assert len(proof.ring_data["commitments"]) == 6

    def test_nullifier_deterministic_per_secret(self):
        """v9: nullifier I=r·H is deterministic per secret (same r → same I)."""
        client = PrivacyPoolClient()
        secret = client.create_deposit("10_erg")
        decoys = [PedersenCommitment.commit(_random_r(), 10 * NANOERG) for _ in range(3)]

        p1 = client.build_withdrawal_proof(secret, decoys, MOCK_ERGO_TREE)
        p2 = client.build_withdrawal_proof(secret, decoys, MOCK_ERGO_TREE)

        # v9: I = r·H is deterministic — same secret → same nullifier
        assert p1.nullifier_hex == p2.nullifier_hex
        assert p1.secondary_gen_hex is None
        assert p2.secondary_gen_hex is None


class TestBuildWithdrawalIntent:
    """Tests for withdrawal intent box construction."""

    def test_basic_intent(self):
        client = PrivacyPoolClient()
        secret = client.create_deposit("10_erg")
        decoys = [PedersenCommitment.commit(_random_r(), 10 * NANOERG) for _ in range(3)]
        proof = client.build_withdrawal_proof(secret, decoys, MOCK_ERGO_TREE)

        intent = client.build_withdrawal_intent(proof)

        assert intent["meta"]["type"] == "IntentToWithdraw"
        assert "R4" in intent["registers"]  # Nullifier
        assert "R6" in intent["registers"]  # Payout address
        # R5 (genesisId) is filled by pool deployer at submission — not set here

    def test_nullifier_in_r4(self):
        client = PrivacyPoolClient()
        secret = client.create_deposit("1_erg")
        decoys = [PedersenCommitment.commit(_random_r(), 1 * NANOERG) for _ in range(3)]
        proof = client.build_withdrawal_proof(secret, decoys, MOCK_ERGO_TREE)

        intent = client.build_withdrawal_intent(proof)
        assert proof.nullifier_hex in intent["registers"]["R4"]


# ==============================================================================
# View Key (Compliance)
# ==============================================================================


class TestViewKey:
    """Tests for view key export and verification."""

    def test_export_view_key(self):
        client = PrivacyPoolClient()
        secret = client.create_deposit("10_erg")
        vk = client.export_view_key(secret)

        assert "blinding_factor_hex" in vk
        assert "commitment" in vk
        assert "amount_nanoerg" in vk
        assert vk["commitment"] == secret.commitment_hex

    def test_verify_view_key(self):
        client = PrivacyPoolClient()
        secret = client.create_deposit("10_erg")

        assert client.verify_view_key(
            secret.commitment_hex, secret.blinding_factor, secret.amount
        )

    def test_wrong_amount_fails_verification(self):
        client = PrivacyPoolClient()
        secret = client.create_deposit("10_erg")

        assert not client.verify_view_key(
            secret.commitment_hex, secret.blinding_factor, secret.amount - 1
        )

    def test_wrong_r_fails_verification(self):
        client = PrivacyPoolClient()
        secret = client.create_deposit("10_erg")

        assert not client.verify_view_key(
            secret.commitment_hex, _random_r(), secret.amount
        )


# ==============================================================================
# Bearer Note Transfer
# ==============================================================================


class TestBearerNote:
    """Tests for bearer note import/export."""

    def test_export_import_roundtrip(self):
        client = PrivacyPoolClient()
        secret = client.create_deposit("1_erg")

        note = client.export_bearer_note(secret)
        restored = client.import_bearer_note(note)

        assert restored.blinding_factor == secret.blinding_factor
        assert restored.commitment_hex == secret.commitment_hex
        assert restored.amount == secret.amount
        assert restored.tier == secret.tier

    def test_note_contains_warning(self):
        client = PrivacyPoolClient()
        secret = client.create_deposit("10_erg")
        note = client.export_bearer_note(secret)

        assert "TRUSTED" in note["warning"]

    def test_tampered_note_rejected(self):
        client = PrivacyPoolClient()
        secret = client.create_deposit("10_erg")
        note = client.export_bearer_note(secret)

        note["amount"] = 999  # Tamper
        with pytest.raises(ValueError, match="integrity check"):
            client.import_bearer_note(note)

    def test_invalid_format_rejected(self):
        with pytest.raises(ValueError, match="Invalid bearer note"):
            PrivacyPoolClient.import_bearer_note({"type": "not_a_note"})

    def test_recipient_can_withdraw(self):
        """Full flow: Alice deposits → exports note → Bob imports → Bob withdraws."""
        client = PrivacyPoolClient()

        # Alice deposits
        alice_secret = client.create_deposit("1_erg")

        # Alice exports bearer note to Bob
        note = client.export_bearer_note(alice_secret)

        # Bob imports
        bob_secret = client.import_bearer_note(note)

        # Bob builds a withdrawal
        decoys = [PedersenCommitment.commit(_random_r(), 1 * NANOERG) for _ in range(3)]
        bob_payout = "0008cd02" + "cc" * 32
        proof = client.build_withdrawal_proof(bob_secret, decoys, bob_payout)

        assert proof.payout_ergo_tree == bob_payout
        assert proof.ring_size == 4


# ==============================================================================
# DepositSecret Serialization
# ==============================================================================


class TestDepositSecretSerialization:
    """Tests for DepositSecret to/from dict."""

    def test_roundtrip(self):
        client = PrivacyPoolClient()
        secret = client.create_deposit("100_erg")

        d = secret.to_dict()
        restored = DepositSecret.from_dict(d)

        assert restored.blinding_factor == secret.blinding_factor
        assert restored.commitment_hex == secret.commitment_hex
        assert restored.amount == secret.amount
        assert restored.tier == secret.tier

    def test_dict_contains_hex_r(self):
        client = PrivacyPoolClient()
        secret = client.create_deposit("10_erg")
        d = secret.to_dict()
        assert d["r"].startswith("0x")


# ==============================================================================
# Pool Status (offline — no node)
# ==============================================================================


class TestPoolStatus:
    """Tests for pool status utilities."""

    def test_no_node_raises(self):
        client = PrivacyPoolClient(node=None)
        with pytest.raises(RuntimeError, match="Node connection required"):
            client.get_pool_status("some_box_id")

    def test_sigma_long_decode(self):
        # Test decoding 0 (05 00 in Sigma)
        assert PrivacyPoolClient._decode_sigma_long("0500") == 0
        # Test decoding 100 = zigzag(100) = 200 = VLQ(c801)
        assert PrivacyPoolClient._decode_sigma_long("05c801") == 100
