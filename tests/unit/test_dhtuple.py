"""
Unit tests for ergo_agent.crypto.dhtuple — DHTuple Ring Signature construction.

All tests are pure math — no network, no mocks. Tests verify the ring
construction, nullifier computation, and integrity checks.
"""

import secrets

import pytest

from ergo_agent.crypto.dhtuple import (
    build_withdrawal_ring,
    compute_nullifier,
    format_context_extension,
    generate_secondary_generator,
    verify_nullifier,
)
from ergo_agent.crypto.pedersen import (
    G_COMPRESSED,
    SECP256K1_N,
    PedersenCommitment,
    decode_point,
    encode_point,
)

# ==============================================================================
# Helpers
# ==============================================================================


def _random_blinding() -> int:
    """Generate a random blinding factor in [1, N-1]."""
    return secrets.randbelow(SECP256K1_N - 1) + 1


def _make_commitment(amount: int) -> tuple[int, str]:
    """Create a random Pedersen commitment, returns (blinding, commitment_hex)."""
    r = _random_blinding()
    C = PedersenCommitment.commit(r, amount)
    return r, C


# ==============================================================================
# Secondary generator tests
# ==============================================================================


class TestSecondaryGenerator:
    """Tests for U generation."""

    def test_valid_point(self):
        """U must be a valid 66-char compressed secp256k1 point."""
        U = generate_secondary_generator()
        assert len(U) == 66
        assert U[:2] in ("02", "03")
        # Must be decodable
        decode_point(U)

    def test_uniqueness(self):
        """Two successive calls should produce different U values."""
        U1 = generate_secondary_generator()
        U2 = generate_secondary_generator()
        assert U1 != U2


# ==============================================================================
# Nullifier tests
# ==============================================================================


class TestNullifier:
    """Tests for I = r·U computation."""

    def test_deterministic(self):
        """Same r and U always produce the same I."""
        r = _random_blinding()
        U = generate_secondary_generator()
        I1 = compute_nullifier(r, U)
        I2 = compute_nullifier(r, U)
        assert I1 == I2

    def test_valid_point(self):
        """Nullifier must be a valid compressed point."""
        r = _random_blinding()
        U = generate_secondary_generator()
        nul = compute_nullifier(r, U)
        assert len(nul) == 66
        decode_point(nul)

    def test_different_r_different_nullifier(self):
        """Different blinding factors produce different nullifiers (linkability)."""
        U = generate_secondary_generator()
        r1 = _random_blinding()
        r2 = _random_blinding()
        assert compute_nullifier(r1, U) != compute_nullifier(r2, U)

    def test_different_U_different_nullifier(self):
        """Same r with different U produces different nullifier (unlinkability)."""
        r = _random_blinding()
        U1 = generate_secondary_generator()
        U2 = generate_secondary_generator()
        assert compute_nullifier(r, U1) != compute_nullifier(r, U2)

    def test_rejects_zero_blinding(self):
        """Zero blinding factor must be rejected."""
        U = generate_secondary_generator()
        with pytest.raises(ValueError, match="blinding_factor"):
            compute_nullifier(0, U)

    def test_verify_roundtrip(self):
        """verify_nullifier must confirm a correctly computed nullifier."""
        r = _random_blinding()
        U = generate_secondary_generator()
        nul = compute_nullifier(r, U)
        assert verify_nullifier(nul, r, U) is True

    def test_verify_wrong_r(self):
        """verify_nullifier must fail with wrong blinding factor."""
        r = _random_blinding()
        U = generate_secondary_generator()
        nul = compute_nullifier(r, U)
        assert verify_nullifier(nul, r + 1, U) is False


# ==============================================================================
# Ring construction tests
# ==============================================================================


class TestBuildWithdrawalRing:
    """Tests for the full ring construction pipeline."""

    def test_ring_contains_real_commitment(self):
        """The real commitment must appear in the ring."""
        r, C_real = _make_commitment(100)
        decoys = [_make_commitment(100)[1] for _ in range(4)]
        ring = build_withdrawal_ring(r, 100, C_real, decoys)
        assert C_real in ring.ring_commitments

    def test_ring_size(self):
        """Ring size = 1 real + N decoys."""
        r, C_real = _make_commitment(100)
        decoys = [_make_commitment(100)[1] for _ in range(7)]
        ring = build_withdrawal_ring(r, 100, C_real, decoys)
        assert ring.ring_size == 8  # 7 decoys + 1 real

    def test_opened_real_equals_rG(self):
        """The opened point at real_index must equal r·G."""
        r, C_real = _make_commitment(100)
        decoys = [_make_commitment(100)[1] for _ in range(3)]
        ring = build_withdrawal_ring(r, 100, C_real, decoys)
        expected_rG = encode_point(r * decode_point(G_COMPRESSED))
        assert ring.opened_points[ring.real_index] == expected_rG

    def test_all_opened_points_valid(self):
        """All opened points must be valid curve points."""
        r, C_real = _make_commitment(100)
        decoys = [_make_commitment(100)[1] for _ in range(3)]
        ring = build_withdrawal_ring(r, 100, C_real, decoys)
        for pt_hex in ring.opened_points:
            assert len(pt_hex) == 66
            decode_point(pt_hex)

    def test_nullifier_verifiable(self):
        """Ring's nullifier must be verifiable with the original blinding factor."""
        r, C_real = _make_commitment(100)
        decoys = [_make_commitment(100)[1] for _ in range(3)]
        ring = build_withdrawal_ring(r, 100, C_real, decoys)
        assert verify_nullifier(ring.nullifier, r, ring.secondary_generator) is True

    def test_wrong_blinding_fails_integrity(self):
        """Ring construction must fail if blinding factor doesn't match commitment."""
        r, C_real = _make_commitment(100)
        wrong_r = _random_blinding()  # Different r
        decoys = [_make_commitment(100)[1] for _ in range(3)]
        with pytest.raises(ValueError, match="integrity check failed"):
            build_withdrawal_ring(wrong_r, 100, C_real, decoys)

    def test_wrong_amount_fails_integrity(self):
        """Ring construction must fail if amount doesn't match commitment."""
        r, C_real = _make_commitment(100)
        decoys = [_make_commitment(100)[1] for _ in range(3)]
        with pytest.raises(ValueError, match="integrity check failed"):
            build_withdrawal_ring(r, 99, C_real, decoys)  # Wrong amount

    def test_no_decoys_rejected(self):
        """At least one decoy is required."""
        r, C_real = _make_commitment(100)
        with pytest.raises(ValueError, match="decoy"):
            build_withdrawal_ring(r, 100, C_real, [])

    def test_custom_secondary_generator(self):
        """Ring should use a pre-supplied U when provided."""
        r, C_real = _make_commitment(100)
        decoys = [_make_commitment(100)[1] for _ in range(3)]
        custom_U = generate_secondary_generator()
        ring = build_withdrawal_ring(r, 100, C_real, decoys, secondary_generator_hex=custom_U)
        assert ring.secondary_generator == custom_U

    def test_real_index_randomized(self):
        """Over many runs, real_index should not always be the same position."""
        r, C_real = _make_commitment(100)
        decoys = [_make_commitment(100)[1] for _ in range(4)]
        indices = set()
        for _ in range(20):
            ring = build_withdrawal_ring(r, 100, C_real, decoys)
            indices.add(ring.real_index)
        # With 5 possible positions and 20 trials, extremely unlikely to always hit one
        assert len(indices) > 1


# ==============================================================================
# Context extension tests
# ==============================================================================


class TestContextExtension:
    """Tests for Sigma-serialized context extension."""

    def test_correct_type_tags(self):
        """Var 0 and Var 1 must have GroupElement type tag 0x07."""
        r, C_real = _make_commitment(100)
        decoys = [_make_commitment(100)[1] for _ in range(3)]
        ring = build_withdrawal_ring(r, 100, C_real, decoys)
        ext = format_context_extension(ring)
        assert ext["0"].startswith("07")  # Nullifier
        assert ext["1"].startswith("07")  # Secondary generator

    def test_correct_lengths(self):
        """Each var should be 2 (type) + 66 (point) = 68 hex chars."""
        r, C_real = _make_commitment(100)
        decoys = [_make_commitment(100)[1] for _ in range(3)]
        ring = build_withdrawal_ring(r, 100, C_real, decoys)
        ext = format_context_extension(ring)
        assert len(ext["0"]) == 68  # 07 + 66-char point
        assert len(ext["1"]) == 68


# ==============================================================================
# ErgoScript proposition tests
# ==============================================================================


class TestErgoScriptProposition:
    """Tests for the formatted ErgoScript sigma proposition."""

    def test_contains_anyOf(self):
        """Proposition must use anyOf()."""
        r, C_real = _make_commitment(100)
        decoys = [_make_commitment(100)[1] for _ in range(2)]
        ring = build_withdrawal_ring(r, 100, C_real, decoys)
        prop = ring.to_ergoscript_proposition()
        assert prop.startswith("anyOf(Coll(")
        assert prop.endswith("))")

    def test_contains_all_proveDHTuple(self):
        """Proposition must have one proveDHTuple per ring member."""
        r, C_real = _make_commitment(100)
        decoys = [_make_commitment(100)[1] for _ in range(2)]
        ring = build_withdrawal_ring(r, 100, C_real, decoys)
        prop = ring.to_ergoscript_proposition()
        assert prop.count("proveDHTuple(") == 3  # 2 decoys + 1 real

    def test_contains_generator_and_nullifier(self):
        """Proposition must reference G, U, and I."""
        r, C_real = _make_commitment(100)
        decoys = [_make_commitment(100)[1] for _ in range(2)]
        ring = build_withdrawal_ring(r, 100, C_real, decoys)
        prop = ring.to_ergoscript_proposition()
        assert G_COMPRESSED in prop
        assert ring.secondary_generator in prop
        assert ring.nullifier in prop
