"""
Unit tests for ergo_agent.relayer.pool_deployer — Chaff & Pool Deployment.

Tests pool deployment, chaff commitment generation,
and multi-tier configuration.
"""

import pytest

from ergo_agent.crypto.pedersen import (
    G_COMPRESSED,
    NUMS_H,
    SECP256K1_P,
    decode_point,
)
from ergo_agent.relayer.deposit_relayer import DepositRelayer
from ergo_agent.relayer.pool_deployer import (
    EMPTY_AVL_TREE_HEX,
    NANOERG,
    POOL_TIERS,
    build_chaff_commitment,
    build_chaff_intent,
    build_genesis_pool_box,
    find_chaff_nonce,
    get_tier_config,
)

# ==============================================================================
# Pool Deployer tests
# ==============================================================================


class TestBuildGenesisPoolBox:
    """Tests for initial MasterPoolBox creation."""

    def test_basic_structure(self):
        box = build_genesis_pool_box(100 * NANOERG, "0008cd02deadbeef")
        assert box["ergoTree"] == "0008cd02deadbeef"
        assert "R4" in box["additionalRegisters"]
        assert "R5" in box["additionalRegisters"]
        assert "R6" in box["additionalRegisters"]
        assert "R7" in box["additionalRegisters"]

    def test_empty_avl_trees(self):
        box = build_genesis_pool_box(100 * NANOERG, "0008cd02deadbeef")
        assert box["additionalRegisters"]["R4"] == EMPTY_AVL_TREE_HEX
        assert box["additionalRegisters"]["R5"] == EMPTY_AVL_TREE_HEX

    def test_counter_starts_at_zero(self):
        box = build_genesis_pool_box(100 * NANOERG, "0008cd02deadbeef")
        r6 = box["additionalRegisters"]["R6"]
        assert r6 == DepositRelayer._sigma_long(0)

    def test_denomination_encoded(self):
        denom = 100 * NANOERG
        box = build_genesis_pool_box(denom, "0008cd02deadbeef")
        r7 = box["additionalRegisters"]["R7"]
        assert r7 == DepositRelayer._sigma_long(denom)

    def test_no_assets(self):
        box = build_genesis_pool_box(100 * NANOERG, "0008cd02deadbeef")
        assert box["assets"] == []


# ==============================================================================
# Chaff Nonce and Commitment tests (M-2 fix)
# ==============================================================================


class TestFindChaffNonce:
    """Tests for the nonce-based hash-to-curve search."""

    def test_returns_valid_commitment(self):
        commitment, nonce = find_chaff_nonce("aa" * 32)
        assert len(commitment) == 66
        assert commitment[:2] == "02"

    def test_commitment_is_on_curve(self):
        commitment, nonce = find_chaff_nonce("bb" * 32)
        pt = decode_point(commitment)
        x, y = pt.x(), pt.y()
        assert (y * y) % SECP256K1_P == (pow(x, 3, SECP256K1_P) + 7) % SECP256K1_P

    def test_deterministic(self):
        c1, n1 = find_chaff_nonce("cc" * 32)
        c2, n2 = find_chaff_nonce("cc" * 32)
        assert c1 == c2
        assert n1 == n2

    def test_different_ids_different_commitments(self):
        c1, _ = find_chaff_nonce("aa" * 32)
        c2, _ = find_chaff_nonce("bb" * 32)
        assert c1 != c2

    def test_nonce_is_4_bytes(self):
        _, nonce = find_chaff_nonce("dd" * 32)
        assert len(nonce) == 8  # 4 bytes = 8 hex chars

    def test_not_generator(self):
        commitment, _ = find_chaff_nonce("ee" * 32)
        assert commitment != G_COMPRESSED

    def test_not_nums_h(self):
        commitment, _ = find_chaff_nonce("ff" * 32)
        assert commitment != NUMS_H


class TestChaffCommitment:
    """Tests for chaff commitment reconstruction (matching on-chain logic)."""

    def test_matches_find_nonce_output(self):
        box_id = "aa" * 32
        expected_commitment, nonce = find_chaff_nonce(box_id)
        reconstructed = build_chaff_commitment(box_id, nonce)
        assert reconstructed == expected_commitment

    def test_invalid_nonce_rejected(self):
        """A nonce that does NOT produce a valid x-coordinate should raise."""
        import hashlib

        box_id = "aa" * 32
        # Try to find a nonce that fails (extremely unlikely but test the path)
        # Instead, pass a known-bad nonce by brute force
        box_bytes = bytes.fromhex(box_id)
        for i in range(1000):
            nonce_bytes = i.to_bytes(4, "big")
            digest = hashlib.blake2b(box_bytes + nonce_bytes, digest_size=32).digest()
            x = int.from_bytes(digest, "big")
            if x >= SECP256K1_P:
                continue
            y_sq = (pow(x, 3, SECP256K1_P) + 7) % SECP256K1_P
            if pow(y_sq, (SECP256K1_P - 1) // 2, SECP256K1_P) != 1:
                # Found a bad nonce
                bad_nonce_hex = nonce_bytes.hex()
                with pytest.raises(ValueError, match="not a QR"):
                    build_chaff_commitment(box_id, bad_nonce_hex)
                return
        # If all tested nonces are valid (astronomically unlikely), skip
        pytest.skip("Could not find a bad nonce for this box ID")

    def test_deterministic(self):
        box_id = "bb" * 32
        _, nonce = find_chaff_nonce(box_id)
        c1 = build_chaff_commitment(box_id, nonce)
        c2 = build_chaff_commitment(box_id, nonce)
        assert c1 == c2


class TestChaffIntent:
    """Tests for chaff IntentToDeposit output building."""

    def test_correct_value(self):
        denom = 100 * NANOERG
        box = build_chaff_intent("aa" * 32, denom, "0008cd03eeeeee")
        assert box["value"] == denom

    def test_has_commitment(self):
        box = build_chaff_intent("aa" * 32, 100 * NANOERG, "0008cd03eeeeee")
        r4 = box["additionalRegisters"]["R4"]
        assert r4.startswith("07")
        assert len(r4) == 68  # 07 + 66 hex chars

    def test_correct_ergo_tree(self):
        tree = "0008cd03eeeeee"
        box = build_chaff_intent("aa" * 32, 100 * NANOERG, tree)
        assert box["ergoTree"] == tree

    def test_has_context_extension(self):
        box = build_chaff_intent("aa" * 32, 100 * NANOERG, "0008cd03eeeeee")
        assert "contextExtension" in box
        assert "0" in box["contextExtension"]

    def test_context_extension_nonce_is_valid(self):
        box_id = "aa" * 32
        box = build_chaff_intent(box_id, 100 * NANOERG, "0008cd03eeeeee")
        nonce = box["contextExtension"]["0"]
        # Reconstruct and verify
        commitment_in_r4 = box["additionalRegisters"]["R4"][2:]  # strip "07"
        reconstructed = build_chaff_commitment(box_id, nonce)
        assert reconstructed == commitment_in_r4


# ==============================================================================
# Tier Configuration tests
# ==============================================================================


class TestTierConfig:
    """Tests for multi-tier pool configuration."""

    def test_1_erg_tier(self):
        tier = get_tier_config("1_erg")
        assert tier["denomination"] == 1 * NANOERG
        assert tier["bounty"] == int(0.01 * NANOERG)

    def test_10_erg_tier(self):
        tier = get_tier_config("10_erg")
        assert tier["denomination"] == 10 * NANOERG
        assert tier["bounty"] == int(0.1 * NANOERG)

    def test_100_erg_tier(self):
        tier = get_tier_config("100_erg")
        assert tier["denomination"] == 100 * NANOERG
        assert tier["bounty"] == int(2.5 * NANOERG)

    def test_unknown_tier_rejected(self):
        with pytest.raises(ValueError, match="Unknown tier"):
            get_tier_config("1000_erg")

    def test_three_tiers_available(self):
        assert len(POOL_TIERS) == 3
