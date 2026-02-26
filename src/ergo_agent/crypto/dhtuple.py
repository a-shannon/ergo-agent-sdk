"""
DHTuple Ring Signature construction for privacy pool withdrawals.

Implements the off-chain ring builder for Ergo's native proveDHTuple
Sigma protocol. The SDK constructs the ring structure and the Ergo
node's built-in Sigma prover generates the actual ZK proof at
transaction signing time.

Mathematical foundation:
    For a withdrawal of `amount` from a ring of Pedersen Commitments {C_0, ..., C_{n-1}}:

    1. Withdrawer picks a random secondary generator U
    2. Nullifier (Key Image): I = r·U  (where r is the blinding factor)
    3. Ring proposition: anyOf([
           proveDHTuple(G, U, C_i - amount·H, I)
           for C_i in ring
       ])

    For the real index j (where C_j = r·G + amount·H):
        C_j - amount·H = r·G
        So proveDHTuple(G, U, r·G, r·U) holds because log_G(r·G) == log_U(r·U) == r

    For decoy indices i ≠ j:
        C_i - amount·H = r_i·G  (different blinding factor)
        proveDHTuple(G, U, r_i·G, r·U) fails because r_i ≠ r

    The anyOf() with the Sigma OR protocol hides which index is real.

Sequential Constraint:
    Ergo's Sigma protocol hashes tx.messageToSign into the Fiat-Shamir
    challenge, so each withdrawal must be processed 1-by-1 sequentially.
    The Relayer cannot batch multiple independent withdrawals.

References:
    [Ergo]  Ergo platform, SigmaState §5.3 — proveDHTuple Sigma protocol.
    [FS07]  Fujisaki & Suzuki, "Traceable Ring Signature", PKC 2007
            (1-out-of-n DH ring signatures).
    [LWW04] Liu, Wei & Wong, "Linkable Spontaneous Anonymous Group Signature",
            ACISP 2004 (per-withdrawal NUMS secondary generator for unlinkability).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from ergo_agent.crypto.pedersen import (
    G_COMPRESSED,
    NUMS_H,
    SECP256K1_N,
    SECP256K1_P,
    decode_point,
    encode_point,
)


# ==============================================================================
# WithdrawalRing — the core ring structure
# ==============================================================================


@dataclass(frozen=True)
class WithdrawalRing:
    """
    A fully constructed DHTuple ring ready for transaction submission.

    Attributes:
        secondary_generator: Compressed hex of U (per-withdrawal random point).
        nullifier: Compressed hex of I = r·U (the key image / nullifier).
        ring_commitments: List of compressed hex commitment points in the ring.
        opened_points: List of compressed hex points (C_i - amount·H) for each ring member.
        amount: The denomination being withdrawn.
        real_index: Index of the real depositor in the ring (for signing).
    """
    secondary_generator: str  # U
    nullifier: str             # I = r·U
    ring_commitments: list[str]  # [C_0, ..., C_{n-1}]
    opened_points: list[str]    # [C_i - amt·H for each C_i]
    amount: int
    real_index: int

    @property
    def ring_size(self) -> int:
        """Number of members in the ring (anonymity set size)."""
        return len(self.ring_commitments)

    def to_ergoscript_proposition(self) -> str:
        """
        Format the ring as an ErgoScript Sigma proposition string.

        Returns the anyOf(proveDHTuple(...)) expression that would appear
        in the MasterPoolBox withdrawal contract.

        Returns:
            ErgoScript source fragment.
        """
        stmts = []
        for opened in self.opened_points:
            stmts.append(
                f'proveDHTuple('
                f'decodePoint(fromBase16("{G_COMPRESSED}")), '
                f'decodePoint(fromBase16("{self.secondary_generator}")), '
                f'decodePoint(fromBase16("{opened}")), '
                f'decodePoint(fromBase16("{self.nullifier}"))'
                f')'
            )
        inner = ", ".join(stmts)
        return f"anyOf(Coll({inner}))"


# ==============================================================================
# Ring construction functions
# ==============================================================================


def generate_secondary_generator() -> str:
    """
    Generate a fresh random secondary generator U for a withdrawal.

    U is a random point on secp256k1 with unknown discrete log.
    Each withdrawal uses a unique U to ensure unlinkability between
    different withdrawals by the same depositor.

    Returns:
        66-char compressed hex of U.
    """
    # Pick a random scalar and multiply by G
    scalar = secrets.randbelow(SECP256K1_N - 1) + 1
    G = decode_point(G_COMPRESSED)
    U = scalar * G
    return encode_point(U)


def compute_nullifier(blinding_factor: int, secondary_generator_hex: str) -> str:
    """
    Compute the nullifier (key image) I = r·U.

    The nullifier uniquely identifies a deposit without revealing which
    commitment it corresponds to. It is inserted into the Nullifier AVL
    Tree to prevent double-spending.

    Args:
        blinding_factor: The depositor's secret blinding factor r.
        secondary_generator_hex: Compressed hex of the secondary generator U.

    Returns:
        66-char compressed hex of I = r·U.

    Raises:
        ValueError: If blinding_factor is out of range.
    """
    if blinding_factor <= 0 or blinding_factor >= SECP256K1_N:
        raise ValueError(
            f"blinding_factor must be in [1, N-1], got {blinding_factor}"
        )

    U = decode_point(secondary_generator_hex)
    I = blinding_factor * U
    return encode_point(I)


def build_withdrawal_ring(
    blinding_factor: int,
    amount: int,
    real_commitment_hex: str,
    decoy_commitment_hexes: list[str],
    secondary_generator_hex: str | None = None,
) -> WithdrawalRing:
    """
    Construct a complete DHTuple withdrawal ring.

    Takes the depositor's real commitment and a set of decoy commitments
    drawn from the Global Deposit Tree, then assembles the ring structure
    needed for the proveDHTuple anyOf() Sigma proposition.

    Args:
        blinding_factor: The depositor's secret r (integer in [1, N-1]).
        amount: The pool denomination (e.g., 100 for 100 ERG pool).
        real_commitment_hex: Compressed hex of the depositor's own commitment C = r·G + amt·H.
        decoy_commitment_hexes: List of compressed hex decoy commitments from the Deposit Tree.
        secondary_generator_hex: Optional pre-generated U. If None, a fresh U is generated.

    Returns:
        WithdrawalRing with the full ring structure ready for transaction building.

    Raises:
        ValueError: If no decoys provided, blinding factor out of range,
                    or real commitment not verifiable.
    """
    if blinding_factor <= 0 or blinding_factor >= SECP256K1_N:
        raise ValueError(
            f"blinding_factor must be in [1, N-1], got {blinding_factor}"
        )
    if amount < 0:
        raise ValueError(f"amount must be non-negative, got {amount}")
    if not decoy_commitment_hexes:
        raise ValueError("At least one decoy commitment is required for a ring")

    # Generate or use provided secondary generator
    if secondary_generator_hex is None:
        secondary_generator_hex = generate_secondary_generator()

    # Compute nullifier I = r·U
    nullifier_hex = compute_nullifier(blinding_factor, secondary_generator_hex)

    # Build the ring: insert real commitment at a random position among decoys
    ring = list(decoy_commitment_hexes)
    real_index = secrets.randbelow(len(ring) + 1)
    ring.insert(real_index, real_commitment_hex)

    # Open each commitment: C_i - amount·H
    H = decode_point(NUMS_H)
    aH = amount * H
    neg_aH = -aH  # Negate once, reuse for all ring members

    opened_points = []
    for c_hex in ring:
        C_i = decode_point(c_hex)
        opened = C_i + neg_aH  # C_i - amount·H
        opened_points.append(encode_point(opened))

    # Sanity check: the opened point at real_index should equal r·G
    G = decode_point(G_COMPRESSED)
    expected_rG = encode_point(blinding_factor * G)
    if opened_points[real_index] != expected_rG:
        raise ValueError(
            "Ring integrity check failed: opened real commitment does not equal r·G. "
            "The blinding factor or real commitment may be incorrect."
        )

    return WithdrawalRing(
        secondary_generator=secondary_generator_hex,
        nullifier=nullifier_hex,
        ring_commitments=ring,
        opened_points=opened_points,
        amount=amount,
        real_index=real_index,
    )


def format_context_extension(ring: WithdrawalRing) -> dict[str, str]:
    """
    Build the Sigma-serialized context extension for a withdrawal transaction.

    Packs the ring data into the context variables expected by the
    MasterPoolBox withdrawal contract:
        Var 0: GroupElement — Nullifier I
        Var 1: GroupElement — Secondary generator U

    Args:
        ring: A fully constructed WithdrawalRing.

    Returns:
        dict mapping string var indices to hex-encoded Sigma values.
    """
    # Var 0: GroupElement (type 0x07 + 33 compressed bytes)
    var0 = "07" + ring.nullifier
    # Var 1: GroupElement (type 0x07 + 33 compressed bytes)
    var1 = "07" + ring.secondary_generator
    return {"0": var0, "1": var1}


def verify_nullifier(
    nullifier_hex: str,
    blinding_factor: int,
    secondary_generator_hex: str,
) -> bool:
    """
    Verify that a nullifier was correctly computed as I = r·U.

    Used by auditors to verify withdrawal provenance when the depositor
    discloses their blinding factor r and the secondary generator U.

    Args:
        nullifier_hex: Compressed hex of the claimed nullifier I.
        blinding_factor: The depositor's blinding factor r.
        secondary_generator_hex: Compressed hex of the secondary generator U.

    Returns:
        True if I == r·U, False otherwise.
    """
    try:
        I = decode_point(nullifier_hex)
        U = decode_point(secondary_generator_hex)
        expected = blinding_factor * U
        return I.x() == expected.x() and I.y() == expected.y()
    except (ValueError, Exception):
        return False
