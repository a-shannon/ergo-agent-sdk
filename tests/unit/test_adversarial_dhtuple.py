"""
Adversarial security tests for ergo_agent.crypto.dhtuple (v9 fixed-H model).

These tests deliberately attempt to break the DHTuple ring signature
construction. Each test class targets a specific attack vector.

v9 CHANGE: U is no longer user-supplied. The nullifier is now I = r·H where
H = NUMS_H is the globally fixed secondary generator. compute_nullifier() now
takes only blinding_factor (no secondary_generator_hex argument).

IMPORTANT: These tests are pure math — no network, no mocks.
If any of these tests FAIL, it means the implementation is vulnerable
to that specific attack class. Every test here MUST pass.
"""

import secrets

import pytest

from ergo_agent.crypto.dhtuple import (
    build_withdrawal_ring,
    compute_nullifier,
    format_context_extension,
    verify_nullifier,
)
from ergo_agent.crypto.pedersen import (
    G_COMPRESSED,
    NUMS_H,
    SECP256K1_N,
    PedersenCommitment,
    decode_point,
    encode_point,
)

# ==============================================================================
# Helpers
# ==============================================================================


def _random_blinding() -> int:
    return secrets.randbelow(SECP256K1_N - 1) + 1


def _make_commitment(amount: int) -> tuple[int, str]:
    r = _random_blinding()
    C = PedersenCommitment.commit(r, amount)
    return r, C


# ==============================================================================
# Attack Vector 1: Nullifier Fixed-H Properties
# ==============================================================================


class TestFixedHNullifier:
    """
    v9 nullifier model: I = r·H (H = NUMS_H, globally fixed).

    The nullifier is deterministic per blinding factor r.
    Changing r always produces a different nullifier (no collisions at human scale).
    The nullifier cannot equal G or H (contract-enforced, tested here at SDK level).
    """

    def test_nullifier_deterministic_for_same_r(self):
        """Same r always produces the same nullifier."""
        r = _random_blinding()
        I1 = compute_nullifier(r)
        I2 = compute_nullifier(r)
        assert I1 == I2

    def test_different_r_different_nullifier(self):
        """Different r values must produce different nullifiers."""
        r1, r2 = _random_blinding(), _random_blinding()
        while r2 == r1:
            r2 = _random_blinding()
        assert compute_nullifier(r1) != compute_nullifier(r2)

    def test_nullifier_equals_r_times_H(self):
        """verify I == r·H exactly."""
        r = _random_blinding()
        H = decode_point(NUMS_H)
        expected = encode_point(r * H)
        assert compute_nullifier(r) == expected

    def test_nullifier_not_generator(self):
        """I = r·H must not equal the base generator G (would be pathological)."""
        for _ in range(20):
            r = _random_blinding()
            assert compute_nullifier(r) != G_COMPRESSED

    def test_nullifier_not_H(self):
        """I = r·H equals H only if r == 1 (mod N). Practically impossible with random r."""
        for _ in range(20):
            r = _random_blinding()
            nullifier_pt = compute_nullifier(r)
            if r != 1:
                assert nullifier_pt != NUMS_H

    def test_50_nullifiers_no_collision(self):
        """50 random nullifiers should all be unique (birthday bound is ~2^128)."""
        nullifiers = set()
        for _ in range(50):
            r = _random_blinding()
            nullifier_pt = compute_nullifier(r)
            assert nullifier_pt not in nullifiers, "Nullifier collision detected"
            nullifiers.add(nullifier_pt)

    def test_zero_scalar_rejected(self):
        """r=0 must be rejected."""
        with pytest.raises(ValueError, match="blinding_factor"):
            compute_nullifier(0)

    def test_order_scalar_rejected(self):
        """r=N must be rejected (≡ 0 mod N)."""
        with pytest.raises(ValueError, match="blinding_factor"):
            compute_nullifier(SECP256K1_N)

    def test_boundary_r1_valid(self):
        """r=1 is valid; I = 1·H = H."""
        nullifier_pt = compute_nullifier(1)
        assert nullifier_pt == NUMS_H  # r=1 → I = H by definition

    def test_boundary_r_n_minus_1_valid(self):
        """r=N-1 is valid (largest valid scalar)."""
        nullifier_pt = compute_nullifier(SECP256K1_N - 1)
        assert len(nullifier_pt) == 66  # Valid compressed point


# ==============================================================================
# Attack Vector 2: Double-Spend Prevention via Fixed Nullifier
# ==============================================================================


class TestDoubleSpendPrevention:
    """
    With fixed H, a depositor cannot generate a fresh nullifier for a second
    withdrawal. The same r always yields the same I = r·H.

    The old variable-U attack (producing I = r·U_n for each fresh U_n) is
    no longer possible — U is not user-supplied.
    """

    def test_double_withdrawal_same_nullifier(self):
        """
        Depositor attempts two withdrawals from the same commitment.
        Both produce the same nullifier → second AVL insert would fail.
        """
        r, C = _make_commitment(10_000_000_000)
        decoys = [_make_commitment(10_000_000_000)[1] for _ in range(3)]

        ring1 = build_withdrawal_ring(r, 10_000_000_000, C, decoys)
        ring2 = build_withdrawal_ring(r, 10_000_000_000, C, decoys)

        assert ring1.nullifier == ring2.nullifier, (
            "Both withdrawal attempts must produce the same nullifier. "
            "The second AVL tree insert would fail (duplicate key), "
            "preventing double-spending."
        )

    def test_nullifier_independent_of_decoy_selection(self):
        """Changing the decoy set does not change the nullifier."""
        r, C = _make_commitment(10_000_000_000)
        decoys_a = [_make_commitment(10_000_000_000)[1] for _ in range(5)]
        decoys_b = [_make_commitment(10_000_000_000)[1] for _ in range(5)]

        ring_a = build_withdrawal_ring(r, 10_000_000_000, C, decoys_a)
        ring_b = build_withdrawal_ring(r, 10_000_000_000, C, decoys_b)

        assert ring_a.nullifier == ring_b.nullifier

    def test_different_depositors_different_nullifiers(self):
        """Two independent depositors with different r values get different nullifiers."""
        amount = 10_000_000_000
        r1, C1 = _make_commitment(amount)
        r2, C2 = _make_commitment(amount)
        decoys = [_make_commitment(amount)[1] for _ in range(3)]

        ring1 = build_withdrawal_ring(r1, amount, C1, decoys)
        ring2 = build_withdrawal_ring(r2, amount, C2, decoys)

        assert ring1.nullifier != ring2.nullifier


# ==============================================================================
# Attack Vector 3: Ring Construction Manipulation
# ==============================================================================


class TestRingManipulation:
    """
    Attempts to manipulate ring construction to break anonymity, cause
    invalid proofs, or leak the real index.
    """

    def test_duplicate_commitment_in_ring(self):
        """Same decoy repeated — valid, anonymity unaffected."""
        r, C_real = _make_commitment(100)
        _, C_decoy = _make_commitment(100)
        ring = build_withdrawal_ring(r, 100, C_real, [C_decoy, C_decoy, C_decoy])
        assert ring.ring_size == 4
        assert C_real in ring.ring_commitments

    def test_real_commitment_also_in_decoys(self):
        """Real commitment appearing as a decoy — slightly stronger anonymity."""
        r, C_real = _make_commitment(100)
        decoys = [C_real, _make_commitment(100)[1], _make_commitment(100)[1]]
        ring = build_withdrawal_ring(r, 100, C_real, decoys)
        assert ring.ring_commitments.count(C_real) >= 2

    def test_minimum_ring_size(self):
        """Ring with 1 decoy (size 2) is valid."""
        r, C_real = _make_commitment(100)
        ring = build_withdrawal_ring(r, 100, C_real, [_make_commitment(100)[1]])
        assert ring.ring_size == 2

    def test_full_k64_ring(self):
        """Ring with 63 decoys (K=64 as per protocol) computes correctly."""
        r, C_real = _make_commitment(100)
        decoys = [_make_commitment(100)[1] for _ in range(63)]
        ring = build_withdrawal_ring(r, 100, C_real, decoys)
        assert ring.ring_size == 64
        G = decode_point(G_COMPRESSED)
        assert ring.opened_points[ring.real_index] == encode_point(r * G)

    def test_real_index_always_in_bounds(self):
        """real_index must always be in [0, ring_size)."""
        r, C_real = _make_commitment(100)
        decoys = [_make_commitment(100)[1] for _ in range(5)]
        for _ in range(50):
            ring = build_withdrawal_ring(r, 100, C_real, decoys)
            assert 0 <= ring.real_index < ring.ring_size

    def test_real_index_uniformly_distributed(self):
        """
        real_index should not be systematically biased (e.g., always 0 or always last).
        With 50 trials over a ring of size 6, we expect some variety.
        """
        r, C_real = _make_commitment(100)
        decoys = [_make_commitment(100)[1] for _ in range(5)]
        indices = {build_withdrawal_ring(r, 100, C_real, decoys).real_index for _ in range(50)}
        assert len(indices) > 1, "real_index appears to be non-random (always same position)"


# ==============================================================================
# Attack Vector 4: Blinding Factor Boundary Conditions
# ==============================================================================


class TestBlindingFactorBoundaries:
    """
    Scalars must be in [1, N-1]. Values at or beyond the boundaries
    could cause silent wrapping, identity-point results, or other
    dangerous behavior.
    """

    def test_reject_negative_blinding(self):
        _, C_real = _make_commitment(100)
        with pytest.raises(ValueError, match="blinding_factor"):
            build_withdrawal_ring(-1, 100, C_real, [_make_commitment(100)[1]])

    def test_reject_blinding_at_order(self):
        _, C_real = _make_commitment(100)
        with pytest.raises(ValueError, match="blinding_factor"):
            build_withdrawal_ring(SECP256K1_N, 100, C_real, [_make_commitment(100)[1]])

    def test_reject_blinding_above_order(self):
        _, C_real = _make_commitment(100)
        with pytest.raises(ValueError, match="blinding_factor"):
            build_withdrawal_ring(SECP256K1_N + 1, 100, C_real, [_make_commitment(100)[1]])

    def test_blinding_factor_one_valid(self):
        C = PedersenCommitment.commit(1, 100)
        ring = build_withdrawal_ring(1, 100, C, [_make_commitment(100)[1]])
        assert ring.ring_size == 2

    def test_blinding_factor_n_minus_1_valid(self):
        C = PedersenCommitment.commit(SECP256K1_N - 1, 100)
        ring = build_withdrawal_ring(SECP256K1_N - 1, 100, C, [_make_commitment(100)[1]])
        assert ring.ring_size == 2

    def test_reject_zero_blinding(self):
        _, C_real = _make_commitment(100)
        with pytest.raises(ValueError, match="blinding_factor"):
            build_withdrawal_ring(0, 100, C_real, [_make_commitment(100)[1]])


# ==============================================================================
# Attack Vector 5: Amount Manipulation
# ==============================================================================


class TestAmountManipulation:
    """
    What if an attacker provides a mismatched amount to build_withdrawal_ring?
    The SDK's integrity check prevents withdrawing a different amount than deposited.
    """

    def test_wrong_amount_fails_integrity_check(self):
        """C was committed for amount=100. Withdrawing with amount=99 must fail."""
        r, C_real = _make_commitment(100)
        with pytest.raises(ValueError, match="integrity check failed"):
            build_withdrawal_ring(r, 99, C_real, [_make_commitment(100)[1]])

    def test_zero_amount_raises(self):
        """Zero-amount deposits have no economic meaning; arithmetic raises."""
        r, C_real = _make_commitment(0)
        with pytest.raises((AttributeError, ValueError, TypeError)):
            build_withdrawal_ring(r, 0, C_real, [_make_commitment(0)[1]])

    def test_negative_amount_rejected(self):
        r = _random_blinding()
        with pytest.raises(ValueError, match="amount"):
            build_withdrawal_ring(r, -1, "02" + "00" * 32, [_make_commitment(100)[1]])


# ==============================================================================
# Attack Vector 6: Malformed Point Injection
# ==============================================================================


class TestMalformedPointInjection:
    """
    What if an attacker injects bytes that look like a compressed point
    but are not on the secp256k1 curve?
    """

    def test_invalid_decoy_not_on_curve(self):
        bad_point = "02" + "00" * 31 + "05"  # x=5 not on secp256k1
        with pytest.raises(ValueError):
            decode_point(bad_point)

    def test_invalid_decoy_causes_ring_failure(self):
        r, C_real = _make_commitment(100)
        bad_decoy = "02" + "00" * 31 + "05"
        with pytest.raises((ValueError, Exception)):
            build_withdrawal_ring(r, 100, C_real, [bad_decoy])

    def test_uncompressed_prefix_rejected(self):
        with pytest.raises(ValueError, match="prefix"):
            decode_point("04" + "ab" * 32)

    def test_wrong_length_rejected(self):
        with pytest.raises(ValueError):
            decode_point("02abcd")

    def test_all_zeros_x_not_on_curve(self):
        with pytest.raises(ValueError):
            decode_point("02" + "00" * 32)


# ==============================================================================
# Attack Vector 7: Context Extension Format
# ==============================================================================


class TestContextExtension:
    """
    Verify the context extension is correctly formatted for v9 MasterPoolBox.
    Var 0: nullifier (GroupElement). Var 1: ring member keys (Coll[Coll[Byte]]).
    U is no longer passed as a context variable.
    """

    def test_context_extension_nullifier_matches_ring(self):
        """Var 0 must carry the ring's nullifier."""
        r, C_real = _make_commitment(100)
        decoys = [_make_commitment(100)[1] for _ in range(3)]
        ring = build_withdrawal_ring(r, 100, C_real, decoys)
        ext = format_context_extension(ring)
        # Strip type tag (07) to get the raw point
        nullifier_from_ext = ext["0"][2:]
        assert nullifier_from_ext == ring.nullifier

    def test_context_extension_has_two_vars(self):
        """v9 extension has Var 0 (nullifier) and Var 1 (ring keys)."""
        r, C_real = _make_commitment(100)
        decoys = [_make_commitment(100)[1] for _ in range(3)]
        ring = build_withdrawal_ring(r, 100, C_real, decoys)
        ext = format_context_extension(ring)
        assert "0" in ext and "1" in ext
        assert len(ext) == 2  # No longer 2 with U; still 2 (nullifier + keys)

    def test_var1_encodes_all_ring_members(self):
        """Var 1 must encode all ring member commitments."""
        r, C_real = _make_commitment(100)
        decoys = [_make_commitment(100)[1] for _ in range(3)]
        ring = build_withdrawal_ring(r, 100, C_real, decoys)
        ext = format_context_extension(ring)
        var1 = ext["1"]
        # Each commitment is 66 hex chars (33 bytes). All 4 should appear in var1.
        for commitment in ring.ring_commitments:
            assert commitment in var1, f"Ring member {commitment[:16]}... not found in Var 1"


# ==============================================================================
# Attack Vector 8: Nullifier Verification
# ==============================================================================


class TestNullifierVerification:
    """
    verify_nullifier(nullifier_pt, r) checks I == r·H. No secondary generator argument.
    """

    def test_correct_nullifier_verifies(self):
        r = _random_blinding()
        nullifier_pt = compute_nullifier(r)
        assert verify_nullifier(nullifier_pt, r) is True

    def test_wrong_r_fails(self):
        r1, r2 = _random_blinding(), _random_blinding()
        while r2 == r1:
            r2 = _random_blinding()
        nullifier_pt = compute_nullifier(r1)
        assert verify_nullifier(nullifier_pt, r2) is False

    def test_random_point_fails(self):
        """A random EC point should not verify as r·H for a given r."""
        r = _random_blinding()
        # Generate a random point (not r·H)
        s = _random_blinding()
        G = decode_point(G_COMPRESSED)
        fake_I = encode_point(s * G)
        # Vanishingly unlikely to equal compute_nullifier(r)
        if fake_I != compute_nullifier(r):
            assert verify_nullifier(fake_I, r) is False

    def test_malformed_nullifier_fails_gracefully(self):
        assert verify_nullifier("deadbeef", 1) is False

    def test_empty_nullifier_fails_gracefully(self):
        assert verify_nullifier("", 1) is False

    def test_boundary_r1(self):
        """r=1 → I = H; verify confirms this."""
        nullifier_pt = compute_nullifier(1)
        assert verify_nullifier(nullifier_pt, 1) is True

    def test_boundary_r_n_minus_1(self):
        nullifier_pt = compute_nullifier(SECP256K1_N - 1)
        assert verify_nullifier(nullifier_pt, SECP256K1_N - 1) is True
