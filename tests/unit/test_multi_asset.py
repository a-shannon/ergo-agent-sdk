"""
Unit tests for ergo_agent.crypto.multi_asset — Multi-Asset Pedersen Commitments.
"""

import secrets

import pytest

from ergo_agent.crypto.pedersen import (
    G_COMPRESSED,
    NUMS_H,
    SECP256K1_N,
    SECP256K1_P,
    decode_point,
    encode_point,
    _GENERATOR,
)
from ergo_agent.crypto.multi_asset import (
    ERG_ASSET_ID,
    MultiAssetCommitment,
    derive_asset_generator,
    prove_multi_asset_balance,
)


def _random_r() -> int:
    return secrets.randbelow(SECP256K1_N - 1) + 1


# ==============================================================================
# Asset Generator Derivation
# ==============================================================================


class TestAssetGenerator:
    """Tests for per-asset NUMS generator derivation."""

    def test_erg_returns_standard_h(self):
        assert derive_asset_generator(ERG_ASSET_ID) == NUMS_H

    def test_token_generator_valid_point(self):
        gen = derive_asset_generator("aa" * 32)
        assert len(gen) == 66
        assert gen[:2] in ("02", "03")
        pt = decode_point(gen)
        x, y = pt.x(), pt.y()
        assert (y * y) % SECP256K1_P == (pow(x, 3, SECP256K1_P) + 7) % SECP256K1_P

    def test_deterministic(self):
        g1 = derive_asset_generator("bb" * 32)
        g2 = derive_asset_generator("bb" * 32)
        assert g1 == g2

    def test_different_tokens_different_generators(self):
        g1 = derive_asset_generator("aa" * 32)
        g2 = derive_asset_generator("bb" * 32)
        assert g1 != g2

    def test_token_generator_not_g(self):
        gen = derive_asset_generator("cc" * 32)
        assert gen != G_COMPRESSED

    def test_token_generator_not_h(self):
        gen = derive_asset_generator("dd" * 32)
        assert gen != NUMS_H


# ==============================================================================
# Multi-Asset Commitment
# ==============================================================================


class TestMultiAssetCommitment:
    """Tests for multi-asset commit/verify."""

    def test_single_erg_commit(self):
        r = _random_r()
        C = MultiAssetCommitment.commit(r, {ERG_ASSET_ID: 100})
        assert MultiAssetCommitment.verify(C, r, {ERG_ASSET_ID: 100})

    def test_multi_asset_commit(self):
        r = _random_r()
        amounts = {ERG_ASSET_ID: 100_000_000_000, "token_abc": 50}
        C = MultiAssetCommitment.commit(r, amounts)
        assert MultiAssetCommitment.verify(C, r, amounts)

    def test_wrong_amount_fails(self):
        r = _random_r()
        amounts = {ERG_ASSET_ID: 100}
        C = MultiAssetCommitment.commit(r, amounts)
        assert not MultiAssetCommitment.verify(C, r, {ERG_ASSET_ID: 99})

    def test_wrong_r_fails(self):
        r = _random_r()
        C = MultiAssetCommitment.commit(r, {ERG_ASSET_ID: 100})
        assert not MultiAssetCommitment.verify(C, _random_r(), {ERG_ASSET_ID: 100})

    def test_missing_asset_fails(self):
        r = _random_r()
        amounts = {ERG_ASSET_ID: 100, "token_x": 50}
        C = MultiAssetCommitment.commit(r, amounts)
        assert not MultiAssetCommitment.verify(C, r, {ERG_ASSET_ID: 100})

    def test_extra_asset_fails(self):
        r = _random_r()
        amounts = {ERG_ASSET_ID: 100}
        C = MultiAssetCommitment.commit(r, amounts)
        assert not MultiAssetCommitment.verify(
            C, r, {ERG_ASSET_ID: 100, "token_x": 1}
        )

    def test_zero_amount_ignored(self):
        r = _random_r()
        C1 = MultiAssetCommitment.commit(r, {ERG_ASSET_ID: 100})
        C2 = MultiAssetCommitment.commit(r, {ERG_ASSET_ID: 100, "token_x": 0})
        assert C1 == C2

    def test_empty_amounts_rejected(self):
        with pytest.raises(ValueError, match="at least one"):
            MultiAssetCommitment.commit(_random_r(), {})

    def test_negative_amount_rejected(self):
        with pytest.raises(ValueError, match="non-negative"):
            MultiAssetCommitment.commit(_random_r(), {ERG_ASSET_ID: -1})


class TestMultiAssetOpen:
    """Tests for selective asset opening."""

    def test_open_reveals_residual(self):
        r = _random_r()
        amounts = {ERG_ASSET_ID: 100, "token_x": 50}
        C = MultiAssetCommitment.commit(r, amounts)

        # Open by subtracting token_x, leaving r·G + 100·H_erg
        residual = MultiAssetCommitment.open_single_asset(
            C, {"token_x": 50}, target_asset=ERG_ASSET_ID
        )
        # Should equal a single-asset commitment to just the ERG amount
        expected = MultiAssetCommitment.commit(r, {ERG_ASSET_ID: 100})
        assert residual == expected


# ==============================================================================
# Multi-Asset Balance Proof
# ==============================================================================


class TestMultiAssetBalance:
    """Tests for multi-asset value conservation."""

    def test_erg_only_balance(self):
        result = prove_multi_asset_balance(
            input_blindings=[_random_r()],
            input_amounts=[{ERG_ASSET_ID: 100}],
            output_blindings=[_random_r(), _random_r()],
            output_amounts=[{ERG_ASSET_ID: 60}, {ERG_ASSET_ID: 40}],
        )
        # Residual should be a valid point
        assert len(result["residual_hex"]) == 66

    def test_multi_asset_balance(self):
        """Both ERG and token amounts must balance."""
        result = prove_multi_asset_balance(
            input_blindings=[_random_r()],
            input_amounts=[{ERG_ASSET_ID: 100, "tok": 50}],
            output_blindings=[_random_r(), _random_r()],
            output_amounts=[
                {ERG_ASSET_ID: 60, "tok": 30},
                {ERG_ASSET_ID: 40, "tok": 20},
            ],
        )
        assert set(result["assets_proven"]) == {ERG_ASSET_ID, "tok"}

        # Verify residual = Δr · G
        D = decode_point(result["residual_hex"])
        expected = result["delta_r"] * _GENERATOR
        assert encode_point(D) == encode_point(expected)

    def test_unbalanced_erg_rejected(self):
        with pytest.raises(ValueError, match="doesn't balance"):
            prove_multi_asset_balance(
                input_blindings=[_random_r()],
                input_amounts=[{ERG_ASSET_ID: 100, "tok": 50}],
                output_blindings=[_random_r()],
                output_amounts=[{ERG_ASSET_ID: 99, "tok": 50}],
            )

    def test_unbalanced_token_rejected(self):
        with pytest.raises(ValueError, match="doesn't balance"):
            prove_multi_asset_balance(
                input_blindings=[_random_r()],
                input_amounts=[{ERG_ASSET_ID: 100, "tok": 50}],
                output_blindings=[_random_r()],
                output_amounts=[{ERG_ASSET_ID: 100, "tok": 49}],
            )

    def test_three_assets_balance(self):
        """Conservation across 3 different asset types."""
        result = prove_multi_asset_balance(
            input_blindings=[_random_r()],
            input_amounts=[{"erg": 100, "tokA": 50, "tokB": 25}],
            output_blindings=[_random_r(), _random_r()],
            output_amounts=[
                {"erg": 70, "tokA": 30, "tokB": 10},
                {"erg": 30, "tokA": 20, "tokB": 15},
            ],
        )
        assert len(result["assets_proven"]) == 3
