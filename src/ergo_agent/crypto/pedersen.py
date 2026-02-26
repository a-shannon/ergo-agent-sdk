"""
Pedersen Commitment primitives for privacy pool homomorphic bridges.

Provides:
- hash_to_curve: NUMS (Nothing-Up-My-Sleeve) generator derivation
- PedersenCommitment: commit / verify / open over secp256k1
- Point encode/decode utilities for compressed secp256k1 points

Mathematical foundation:
    C = r·G + amount·H
    where H = hash_to_curve(G) is a NUMS point with unknown discrete log w.r.t. G.
    Verification: (C - amount·H) == r·G  — checkable via native proveDlog on-chain.

References:
    [Ped91] T.P. Pedersen, "Non-Interactive and Information-Theoretic Secure
            Verifiable Secret Sharing", CRYPTO '91, §3.
    [H2C]   IETF draft-irtf-cfrg-hash-to-curve, §5 (try-and-increment method).
    [Ergo]  Ergo platform uses Blake2b256 as the canonical hash function;
            all protocol-level hashing must use Blake2b256 (not SHA-256).
"""

from __future__ import annotations

import hashlib

import ecdsa
import ecdsa.ellipticcurve as ec

# ==============================================================================
# secp256k1 curve constants
# ==============================================================================

# Field prime
SECP256K1_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F

# Group order
SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141

# Generator point (compressed)
G_COMPRESSED = "0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"

# The secp256k1 curve object from the ecdsa library
_CURVE = ecdsa.SECP256k1.curve
_GENERATOR = ecdsa.SECP256k1.generator


# ==============================================================================
# Point utilities (public API)
# ==============================================================================


def decode_point(hex_str: str) -> ec.PointJacobi:
    """
    Decode a 33-byte compressed secp256k1 point to an ecdsa Point.

    Args:
        hex_str: 66-character hex string (02/03 prefix + 32-byte X coordinate).

    Returns:
        ecdsa elliptic curve Point.

    Raises:
        ValueError: If the hex string is malformed or not on the curve.
    """
    raw = bytes.fromhex(hex_str)
    if len(raw) != 33:
        raise ValueError(f"Expected 33 bytes, got {len(raw)}")
    prefix = raw[0]
    if prefix not in (0x02, 0x03):
        raise ValueError(f"Invalid prefix byte: 0x{prefix:02x}")

    x = int.from_bytes(raw[1:], "big")
    y_sq = (pow(x, 3, SECP256K1_P) + 7) % SECP256K1_P
    y = pow(y_sq, (SECP256K1_P + 1) // 4, SECP256K1_P)

    # Verify it's actually a quadratic residue (point is on curve)
    if (y * y) % SECP256K1_P != y_sq:
        raise ValueError(f"X coordinate 0x{x:064x} does not correspond to a curve point")

    is_even = (prefix == 0x02)
    if (y % 2 == 0) != is_even:
        y = SECP256K1_P - y

    return ec.PointJacobi(_CURVE, x, y, 1)


def encode_point(pt: ec.AbstractPoint) -> str:
    """
    Encode an ecdsa Point as a 33-byte compressed hex string.

    Args:
        pt: An ecdsa elliptic curve point.

    Returns:
        66-character hex string with 02/03 prefix.

    Raises:
        ValueError: If the point is the identity (point at infinity).
    """
    if pt == ec.INFINITY:
        raise ValueError("Cannot encode the point at infinity")
    prefix = b"\x02" if pt.y() % 2 == 0 else b"\x03"
    return (prefix + pt.x().to_bytes(32, "big")).hex()


# ==============================================================================
# hash_to_curve — NUMS generator derivation
# ==============================================================================


def hash_to_curve(seed_point_hex: str) -> str:
    """
    Derive a Nothing-Up-My-Sleeve (NUMS) secondary generator via hash-to-curve.

    Takes the compressed encoding of a known generator point, hashes it with
    Blake2b256 to produce a candidate x-coordinate, and increments until a valid
    secp256k1 point is found. The resulting point has no known discrete log
    relationship to the input generator.

    Algorithm (try-and-increment, per IETF hash-to-curve §5):
        1. x = int(Blake2b256(compressed_point_bytes)) mod p
        2. While x³+7 mod p is not a quadratic residue: x += 1
        3. Compute y = sqrt(x³+7) mod p, choose even y (0x02 prefix)

    Uses Blake2b256 (Ergo's canonical hash) instead of SHA-256.
    Reference: [Ped91] §3, [H2C] §5.

    Args:
        seed_point_hex: 66-char compressed hex of the seed generator (e.g., G).

    Returns:
        66-char compressed hex of the NUMS point (always with 0x02 prefix / even y).
    """
    seed_bytes = bytes.fromhex(seed_point_hex)
    if len(seed_bytes) != 33:
        raise ValueError(f"Seed point must be 33 bytes, got {len(seed_bytes)}")

    # Blake2b256 — Ergo's canonical hash function
    digest = hashlib.blake2b(seed_bytes, digest_size=32).digest()
    x = int.from_bytes(digest, "big") % SECP256K1_P

    # Increment x until we find a valid curve point
    for _ in range(1000):
        y_sq = (pow(x, 3, SECP256K1_P) + 7) % SECP256K1_P
        # Euler criterion: y_sq is a QR iff y_sq^((p-1)/2) == 1 mod p
        if pow(y_sq, (SECP256K1_P - 1) // 2, SECP256K1_P) == 1:
            y = pow(y_sq, (SECP256K1_P + 1) // 4, SECP256K1_P)
            # Normalize to even y (0x02 prefix)
            if y % 2 != 0:
                y = SECP256K1_P - y
            return (b"\x02" + x.to_bytes(32, "big")).hex()
        x = (x + 1) % SECP256K1_P

    raise RuntimeError("hash_to_curve: failed to find a valid point in 1000 iterations")


# ==============================================================================
# Module-level NUMS constant
# ==============================================================================

NUMS_H = hash_to_curve(G_COMPRESSED)
"""The NUMS secondary generator H = hash_to_curve(G), used for Pedersen Commitments."""

# Pre-decoded H point for internal arithmetic
_H_POINT = decode_point(NUMS_H)


# ==============================================================================
# PedersenCommitment
# ==============================================================================


class PedersenCommitment:
    """
    Pedersen Commitment scheme over secp256k1.

    A commitment C = r·G + amount·H is:
    - **Hiding**: reveals nothing about `amount` without `r`
    - **Binding**: cannot open to a different `(r', amount')` pair
    - **Homomorphic**: C1 + C2 = (r1+r2)·G + (a1+a2)·H

    The secondary generator H is derived as NUMS via hash_to_curve(G).
    """

    @staticmethod
    def commit(blinding_factor: int, amount: int) -> str:
        """
        Create a Pedersen Commitment C = r·G + amount·H.

        Args:
            blinding_factor: The random blinding factor r (integer in [1, N-1]).
            amount: The committed value (non-negative integer).

        Returns:
            66-char compressed hex of the commitment point C.

        Raises:
            ValueError: If blinding_factor is out of range or amount is negative.
        """
        if blinding_factor <= 0 or blinding_factor >= SECP256K1_N:
            raise ValueError(
                f"blinding_factor must be in [1, N-1], got {blinding_factor}"
            )
        if amount < 0:
            raise ValueError(f"amount must be non-negative, got {amount}")

        # C = r·G + amount·H
        rG = blinding_factor * _GENERATOR
        aH = amount * _H_POINT
        C = rG + aH
        return encode_point(C)

    @staticmethod
    def verify(commitment_hex: str, blinding_factor: int, amount: int) -> bool:
        """
        Verify a Pedersen Commitment: check that C == r·G + amount·H.

        Args:
            commitment_hex: 66-char compressed hex of the commitment C.
            blinding_factor: The blinding factor r.
            amount: The claimed committed value.

        Returns:
            True if C == r·G + amount·H, False otherwise.
        """
        try:
            C = decode_point(commitment_hex)
            expected = blinding_factor * _GENERATOR + amount * _H_POINT
            return C.x() == expected.x() and C.y() == expected.y()
        except (ValueError, Exception):
            return False

    @staticmethod
    def open(commitment_hex: str, amount: int) -> str:
        """
        Open a commitment by subtracting amount·H, yielding r·G.

        This is the value used for on-chain proveDlog verification:
        the ErgoScript contract computes (C - amount·H) and verifies
        via proveDlog that the depositor knows r.

        Args:
            commitment_hex: 66-char compressed hex of the commitment C.
            amount: The committed denomination.

        Returns:
            66-char compressed hex of (C - amount·H) = r·G.

        Raises:
            ValueError: If commitment_hex is invalid.
        """
        C = decode_point(commitment_hex)
        aH = amount * _H_POINT
        # C - amount·H = r·G
        rG = C + (-aH)
        return encode_point(rG)
