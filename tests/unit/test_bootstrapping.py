"""
Unit tests for ergo_agent.relayer.pool_deployer — Genesis Lock & Chaff.

Tests pool deployment, Genesis Lock threshold, chaff commitment generation,
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
    GENESIS_THRESHOLD,
    NANOERG,
    POOL_TIERS,
    build_chaff_commitment,
    build_chaff_intent,
    build_genesis_pool_box,
    get_tier_config,
    is_pool_unlocked,
)

# ==============================================================================
# Genesis Lock tests
# ==============================================================================


class TestGenesisLock:
    """Tests for the Genesis Lock threshold."""

    def test_locked_at_zero(self):
        assert is_pool_unlocked(0) is False

    def test_locked_at_99(self):
        assert is_pool_unlocked(99) is False

    def test_unlocked_at_100(self):
        assert is_pool_unlocked(100) is True

    def test_unlocked_at_101(self):
        assert is_pool_unlocked(101) is True

    def test_unlocked_at_1000(self):
        assert is_pool_unlocked(1000) is True

    def test_threshold_constant(self):
        assert GENESIS_THRESHOLD == 100


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
# Chaff Commitment tests
# ==============================================================================


class TestChaffCommitment:
    """Tests for chaff (dummy) commitment generation."""

    def test_valid_point(self):
        C = build_chaff_commitment("aa" * 16)
        assert len(C) == 66
        assert C[:2] in ("02", "03")
        # Must be on curve
        pt = decode_point(C)
        x, y = pt.x(), pt.y()
        assert (y * y) % SECP256K1_P == (pow(x, 3, SECP256K1_P) + 7) % SECP256K1_P

    def test_deterministic(self):
        C1 = build_chaff_commitment("bb" * 16)
        C2 = build_chaff_commitment("bb" * 16)
        assert C1 == C2

    def test_different_seeds_different_commitments(self):
        C1 = build_chaff_commitment("aa" * 16)
        C2 = build_chaff_commitment("bb" * 16)
        assert C1 != C2

    def test_not_generator(self):
        C = build_chaff_commitment("cc" * 16)
        assert C != G_COMPRESSED

    def test_not_nums_h(self):
        C = build_chaff_commitment("dd" * 16)
        assert C != NUMS_H


class TestChaffIntent:
    """Tests for chaff IntentToDeposit output building."""

    def test_correct_value(self):
        denom = 100 * NANOERG
        box = build_chaff_intent("aa" * 16, denom, "0008cd03eeeeee")
        assert box["value"] == denom

    def test_has_commitment(self):
        box = build_chaff_intent("aa" * 16, 100 * NANOERG, "0008cd03eeeeee")
        r4 = box["additionalRegisters"]["R4"]
        assert r4.startswith("07")
        assert len(r4) == 68  # 07 + 66 hex chars

    def test_correct_ergo_tree(self):
        tree = "0008cd03eeeeee"
        box = build_chaff_intent("aa" * 16, 100 * NANOERG, tree)
        assert box["ergoTree"] == tree


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
