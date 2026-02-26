"""
Unit tests for ergo_agent.crypto.pedersen — Pedersen Commitments & NUMS generation.

All tests are pure math — no network, no mocks, no external dependencies
beyond the ecdsa library.
"""

import secrets

import pytest

from ergo_agent.crypto.pedersen import (
    G_COMPRESSED,
    NUMS_H,
    SECP256K1_N,
    SECP256K1_P,
    PedersenCommitment,
    decode_point,
    encode_point,
    hash_to_curve,
)


# ==============================================================================
# hash_to_curve tests
# ==============================================================================


class TestHashToCurve:
    """Tests for the NUMS generator derivation."""

    def test_deterministic(self):
        """Same input always produces the same output."""
        h1 = hash_to_curve(G_COMPRESSED)
        h2 = hash_to_curve(G_COMPRESSED)
        assert h1 == h2

    def test_on_curve(self):
        """Output point must satisfy y² = x³ + 7 mod p."""
        pt = decode_point(NUMS_H)
        x, y = pt.x(), pt.y()
        assert (y * y) % SECP256K1_P == (pow(x, 3, SECP256K1_P) + 7) % SECP256K1_P

    def test_not_generator(self):
        """H must not equal G (would break binding property)."""
        assert NUMS_H != G_COMPRESSED

    def test_even_y_prefix(self):
        """hash_to_curve always returns a point with 0x02 prefix (even y)."""
        assert NUMS_H.startswith("02")

    def test_valid_length(self):
        """Output is exactly 66 hex chars (33 bytes)."""
        assert len(NUMS_H) == 66

    def test_different_seed_different_output(self):
        """Different seed points produce different NUMS generators."""
        # Use an arbitrary valid point (2·G)
        two_g = encode_point(2 * decode_point(G_COMPRESSED))
        h_from_2g = hash_to_curve(two_g)
        assert h_from_2g != NUMS_H

    def test_invalid_seed_length(self):
        """Must reject seeds that aren't 33 bytes."""
        with pytest.raises(ValueError, match="33 bytes"):
            hash_to_curve("0279be667ef9dcbbac")  # too short


# ==============================================================================
# Point encode/decode tests
# ==============================================================================


class TestPointCodec:
    """Tests for point serialization."""

    def test_roundtrip_generator(self):
        """Encode(Decode(G)) == G."""
        pt = decode_point(G_COMPRESSED)
        assert encode_point(pt) == G_COMPRESSED

    def test_roundtrip_nums_h(self):
        """Encode(Decode(H)) == H."""
        pt = decode_point(NUMS_H)
        assert encode_point(pt) == NUMS_H

    def test_roundtrip_random_point(self):
        """Random scalar × G roundtrips correctly."""
        scalar = secrets.randbelow(SECP256K1_N - 1) + 1
        pt = scalar * decode_point(G_COMPRESSED)
        hex_str = encode_point(pt)
        pt2 = decode_point(hex_str)
        assert pt2.x() == pt.x() and pt2.y() == pt.y()

    def test_decode_invalid_prefix(self):
        """Must reject points with prefix other than 02/03."""
        bad_hex = "04" + "aa" * 32
        with pytest.raises(ValueError, match="Invalid prefix"):
            decode_point(bad_hex)

    def test_decode_wrong_length(self):
        """Must reject hex that isn't 33 bytes."""
        with pytest.raises(ValueError, match="33 bytes"):
            decode_point("02aabb")


# ==============================================================================
# PedersenCommitment tests
# ==============================================================================


class TestPedersenCommitment:
    """Tests for commit / verify / open."""

    def test_commit_produces_valid_point(self):
        """Commitment output is a valid 66-char hex compressed point."""
        r = secrets.randbelow(SECP256K1_N - 1) + 1
        C = PedersenCommitment.commit(r, 100)
        assert len(C) == 66
        assert C[:2] in ("02", "03")
        # Must be decodable (on curve)
        decode_point(C)

    def test_verify_roundtrip(self):
        """verify(commit(r, amt), r, amt) must return True."""
        r = secrets.randbelow(SECP256K1_N - 1) + 1
        amt = 100
        C = PedersenCommitment.commit(r, amt)
        assert PedersenCommitment.verify(C, r, amt) is True

    def test_verify_wrong_amount(self):
        """Changing the amount by even 1 must fail verification."""
        r = secrets.randbelow(SECP256K1_N - 1) + 1
        C = PedersenCommitment.commit(r, 100)
        assert PedersenCommitment.verify(C, r, 99) is False
        assert PedersenCommitment.verify(C, r, 101) is False

    def test_verify_wrong_blinding(self):
        """Wrong blinding factor must fail verification."""
        r = secrets.randbelow(SECP256K1_N - 2) + 1
        C = PedersenCommitment.commit(r, 100)
        assert PedersenCommitment.verify(C, r + 1, 100) is False

    def test_open_returns_rG(self):
        """open(C, amount) must equal encode_point(r·G)."""
        r = secrets.randbelow(SECP256K1_N - 1) + 1
        amt = 100
        C = PedersenCommitment.commit(r, amt)
        opened = PedersenCommitment.open(C, amt)
        expected_rG = encode_point(r * decode_point(G_COMPRESSED))
        assert opened == expected_rG

    def test_zero_amount_commit(self):
        """commit(r, 0) should equal r·G (no H component)."""
        r = secrets.randbelow(SECP256K1_N - 1) + 1
        C = PedersenCommitment.commit(r, 0)
        rG = encode_point(r * decode_point(G_COMPRESSED))
        assert C == rG

    def test_homomorphic_addition(self):
        """C1 + C2 should correspond to (r1+r2, a1+a2) — homomorphic property."""
        r1 = secrets.randbelow(SECP256K1_N - 1) + 1
        r2 = secrets.randbelow(SECP256K1_N - 1) + 1
        a1, a2 = 50, 75
        C1 = decode_point(PedersenCommitment.commit(r1, a1))
        C2 = decode_point(PedersenCommitment.commit(r2, a2))
        C_sum = C1 + C2
        r_sum = (r1 + r2) % SECP256K1_N
        C_expected = PedersenCommitment.commit(r_sum, a1 + a2)
        assert encode_point(C_sum) == C_expected

    def test_commit_rejects_zero_blinding(self):
        """Blinding factor of 0 must be rejected."""
        with pytest.raises(ValueError, match="blinding_factor"):
            PedersenCommitment.commit(0, 100)

    def test_commit_rejects_negative_amount(self):
        """Negative amounts must be rejected."""
        r = secrets.randbelow(SECP256K1_N - 1) + 1
        with pytest.raises(ValueError, match="non-negative"):
            PedersenCommitment.commit(r, -1)

    def test_large_denomination(self):
        """Commitments work with large denomination values (e.g., 1000 ERG in nanoERG)."""
        r = secrets.randbelow(SECP256K1_N - 1) + 1
        amt = 1_000_000_000_000  # 1000 ERG in nanoERG
        C = PedersenCommitment.commit(r, amt)
        assert PedersenCommitment.verify(C, r, amt) is True
        assert PedersenCommitment.verify(C, r, amt - 1) is False
