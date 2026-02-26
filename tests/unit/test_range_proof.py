"""
Unit tests for ergo_agent.crypto.range_proof — Range Proofs & Balance Proofs.
"""

import secrets

import pytest

from ergo_agent.crypto.pedersen import (
    G_COMPRESSED,
    SECP256K1_N,
    PedersenCommitment,
    decode_point,
    encode_point,
    _GENERATOR,
)
from ergo_agent.crypto.range_proof import (
    MAX_VALUE,
    BIT_LENGTH,
    RangeProof,
    BalanceProof,
    prove_range,
    verify_range,
    prove_balance,
    verify_balance,
)


def _random_r() -> int:
    return secrets.randbelow(SECP256K1_N - 1) + 1


# ==============================================================================
# Range Proof tests
# ==============================================================================


class TestRangeProof:
    """Tests for bit-decomposition range proofs."""

    def test_small_value(self):
        r = _random_r()
        proof = prove_range(r, 42)
        assert verify_range(proof)

    def test_zero_value(self):
        r = _random_r()
        proof = prove_range(r, 0)
        assert verify_range(proof)

    def test_large_value(self):
        r = _random_r()
        proof = prove_range(r, MAX_VALUE)
        assert verify_range(proof)

    def test_power_of_two(self):
        r = _random_r()
        proof = prove_range(r, 2**32)
        assert verify_range(proof)

    def test_commitment_matches(self):
        r = _random_r()
        v = 1_000_000_000
        proof = prove_range(r, v)
        expected = PedersenCommitment.commit(r, v)
        assert proof.commitment_hex == expected

    def test_bit_length_correct(self):
        r = _random_r()
        proof = prove_range(r, 100)
        assert proof.bit_length == BIT_LENGTH
        assert len(proof.bit_commitments) == BIT_LENGTH

    def test_negative_value_rejected(self):
        r = _random_r()
        with pytest.raises(ValueError, match="out of range"):
            prove_range(r, -1)

    def test_overflow_value_rejected(self):
        r = _random_r()
        with pytest.raises(ValueError, match="out of range"):
            prove_range(r, MAX_VALUE + 1)

    def test_invalid_blinding_rejected(self):
        with pytest.raises(ValueError, match="Blinding factor"):
            prove_range(0, 100)

    def test_different_values_different_proofs(self):
        r = _random_r()
        p1 = prove_range(r, 100)
        r2 = _random_r()
        p2 = prove_range(r2, 200)
        assert p1.commitment_hex != p2.commitment_hex

    def test_tampered_proof_fails(self):
        r = _random_r()
        proof = prove_range(r, 42)
        # Tamper with one bit commitment
        tampered_bits = list(proof.bit_commitments)
        tampered_bits[0] = PedersenCommitment.commit(_random_r(), 1)
        tampered = RangeProof(
            commitment_hex=proof.commitment_hex,
            bit_commitments=tampered_bits,
            proof_hash=proof.proof_hash,
        )
        assert not verify_range(tampered)


# ==============================================================================
# Balance Proof tests
# ==============================================================================


class TestBalanceProof:
    """Tests for value conservation proofs."""

    def test_simple_1_to_2_split(self):
        """100 ERG → 60 ERG + 40 ERG."""
        r_in = _random_r()
        r_out1 = _random_r()
        r_out2 = _random_r()

        proof = prove_balance(
            input_blindings=[r_in],
            input_amounts=[100],
            output_blindings=[r_out1, r_out2],
            output_amounts=[60, 40],
        )
        assert verify_balance(proof)

    def test_2_to_1_merge(self):
        """30 + 70 → 100."""
        r1 = _random_r()
        r2 = _random_r()
        r_out = _random_r()

        proof = prove_balance(
            input_blindings=[r1, r2],
            input_amounts=[30, 70],
            output_blindings=[r_out],
            output_amounts=[100],
        )
        assert verify_balance(proof)

    def test_equal_split(self):
        """50 → 25 + 25."""
        proof = prove_balance(
            input_blindings=[_random_r()],
            input_amounts=[50],
            output_blindings=[_random_r(), _random_r()],
            output_amounts=[25, 25],
        )
        assert verify_balance(proof)

    def test_identity_transfer(self):
        """100 → 100 (same value, different blinding)."""
        proof = prove_balance(
            input_blindings=[_random_r()],
            input_amounts=[100],
            output_blindings=[_random_r()],
            output_amounts=[100],
        )
        assert verify_balance(proof)

    def test_unbalanced_rejected(self):
        """Values don't sum: 100 ≠ 99 + 2."""
        with pytest.raises(ValueError, match="don't balance"):
            prove_balance(
                input_blindings=[_random_r()],
                input_amounts=[100],
                output_blindings=[_random_r(), _random_r()],
                output_amounts=[99, 2],
            )

    def test_residual_is_pure_g_multiple(self):
        """The residual must be Δr · G."""
        r_in = _random_r()
        r_out = _random_r()

        proof = prove_balance(
            input_blindings=[r_in],
            input_amounts=[100],
            output_blindings=[r_out],
            output_amounts=[100],
        )

        # D = Δr · G
        D = decode_point(proof.residual_hex)
        expected_D = proof.delta_r * _GENERATOR
        assert encode_point(D) == encode_point(expected_D)

    def test_large_values(self):
        """Conservation with nanoERG-scale values."""
        proof = prove_balance(
            input_blindings=[_random_r()],
            input_amounts=[100_000_000_000],  # 100 ERG
            output_blindings=[_random_r(), _random_r()],
            output_amounts=[60_000_000_000, 40_000_000_000],
        )
        assert verify_balance(proof)
