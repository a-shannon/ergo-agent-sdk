"""
DHTuple Ring Signature construction for privacy pool withdrawals.

Implements the off-chain ring builder for Ergo's native proveDHTuple
Sigma protocol. The SDK constructs the ring structure and the Ergo
node's built-in Sigma prover generates the actual ZK proof at
transaction signing time.

Mathematical foundation:
    For a withdrawal of `amount` from a ring of Pedersen Commitments {C_0, ..., C_{n-1}}:

    1. Nullifier (Key Image): I = r·H  (H = U_global, the globally fixed NUMS generator)
    2. Ring proposition: anyOf([
           proveDHTuple(G, H, C_i - amount·H, I)
           for C_i in ring
       ])

    For the real index j (where C_j = r·G + amount·H):
        C_j - amount·H = r·G
        So proveDHTuple(G, H, r·G, r·H) holds because log_G(r·G) == log_H(r·H) == r

    For decoy indices i ≠ j:
        C_i - amount·H = r_i·G  (different blinding factor)
        proveDHTuple(G, H, r_i·G, r·H) fails because r_i ≠ r

    The anyOf() with the Sigma OR protocol hides which index is real.

v9 Security Changes (CRIT-2 fix):
    - U is no longer user-supplied per withdrawal.
    - U_global = H (the NUMS generator) is hardcoded in the MasterPoolBox contract.
    - Nullifier is now deterministic per secret key r: I = r·H.
    - This prevents double-spending via fresh-U reuse: the same r always produces
      the same I, so the AVL tree's duplicate-insert check reliably prevents replay.

Sequential Constraint:
    Ergo's Sigma protocol hashes tx.messageToSign into the Fiat-Shamir
    challenge, so each withdrawal must be processed 1-by-1 sequentially.
    Users must construct, sign, and broadcast the withdrawal TX interactively
    (HIGH-1 clarification: pre-signed proofs cannot be relayed asynchronously).

Context Extension for MasterPoolBox (v9):
    Var 0: GroupElement — Nullifier I = r·H
    Var 1: Coll[Coll[Byte]] — Ring member public keys (compressed hex)
    (U is no longer passed as a context variable — it's hardcoded as H in the contract)

References:
    [Ergo]  Ergo platform, SigmaState §5.3 — proveDHTuple Sigma protocol.
    [FS07]  Fujisaki & Suzuki, "Traceable Ring Signature", PKC 2007.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from ergo_agent.crypto.pedersen import (
    G_COMPRESSED,
    NUMS_H,
    SECP256K1_N,
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
        nullifier: Compressed hex of I = r·H (the key image / nullifier).
        ring_commitments: List of compressed hex commitment points in the ring.
        opened_points: List of compressed hex points (C_i - amount·H) for each ring member.
        amount: The denomination being withdrawn in nanoERG.
        real_index: Index of the real depositor in the ring (for signing).
    """
    nullifier: str               # I = r·H
    ring_commitments: list[str]  # [C_0, ..., C_{n-1}]
    opened_points: list[str]     # [C_i - amt·H for each C_i]
    amount: int
    real_index: int

    @property
    def ring_size(self) -> int:
        """Number of members in the ring."""
        return len(self.ring_commitments)

    def to_ergoscript_proposition(self) -> str:
        """
        Format the ring as an ErgoScript Sigma proposition string.

        Returns the anyOf(proveDHTuple(...)) expression that would appear
        in the MasterPoolBox withdrawal contract. U = H (hardcoded in contract).

        Returns:
            ErgoScript source fragment.
        """
        stmts = []
        for opened in self.opened_points:
            stmts.append(
                f'proveDHTuple('
                f'decodePoint(fromBase16("{G_COMPRESSED}")), '
                f'decodePoint(fromBase16("{NUMS_H}")), '
                f'decodePoint(fromBase16("{opened}")), '
                f'decodePoint(fromBase16("{self.nullifier}"))'
                f')'
            )
        inner = ", ".join(stmts)
        return f"anyOf(Coll({inner}))"


# ==============================================================================
# Core functions
# ==============================================================================


def compute_nullifier(blinding_factor: int) -> str:
    """
    Compute the nullifier (key image) I = r·H.

    H = NUMS_H is the globally fixed secondary generator (U_global).
    The nullifier is strictly deterministic per secret key r — no
    user-supplied parameter. This prevents double-spending via fresh-U
    reuse (CRIT-2 fix).

    Args:
        blinding_factor: The depositor's secret blinding factor r.

    Returns:
        66-char compressed hex of I = r·H.

    Raises:
        ValueError: If blinding_factor is out of range [1, N-1].
    """
    if blinding_factor <= 0 or blinding_factor >= SECP256K1_N:
        raise ValueError(
            f"blinding_factor must be in [1, N-1], got {blinding_factor}"
        )
    H = decode_point(NUMS_H)
    return encode_point(blinding_factor * H)


def build_withdrawal_ring(
    blinding_factor: int,
    amount: int,
    real_commitment_hex: str,
    decoy_commitment_hexes: list[str],
) -> WithdrawalRing:
    """
    Construct a complete DHTuple withdrawal ring.

    Takes the depositor's real commitment and a set of decoy commitments
    drawn from the Global Deposit Tree, then assembles the ring structure
    needed for the proveDHTuple anyOf() Sigma proposition.

    Nullifier is computed as I = r·H (U_global = H, CRIT-2 fix).

    Args:
        blinding_factor: The depositor's secret r (integer in [1, N-1]).
        amount: The pool denomination in nanoERG (e.g., 10_000_000_000 for 10 ERG).
        real_commitment_hex: Compressed hex of the depositor's own commitment C = r·G + amt·H.
        decoy_commitment_hexes: List of compressed hex decoy commitments from the Deposit Tree.

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

    # Compute nullifier I = r·H (fixed NUMS generator, no user-supplied U)
    nullifier_hex = compute_nullifier(blinding_factor)

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
    MasterPoolBox withdrawal contract (v9):
        Var 0: GroupElement — Nullifier I = r·H
        Var 1: Coll[Coll[Byte]] — ring member public keys (compressed hex)

    Note: In v9, U (secondary generator) is no longer passed as a context
    variable — it is hardcoded as H (NUMS_H) inside the MasterPoolBox contract.

    Args:
        ring: A fully constructed WithdrawalRing.

    Returns:
        dict mapping string var indices to hex-encoded Sigma values.
    """
    # Var 0: GroupElement (type 0x07 + 33 compressed bytes)
    var0 = "07" + ring.nullifier

    # Var 1: Coll[Coll[Byte]] — ring member keys
    # Each key is a 33-byte compressed point; Sigma serialisation:
    # type tag 0x0c (Coll[Byte]), then length-prefixed bytes per member
    # Packed as outer Coll[Coll[Byte]] (type 0x0c0c)
    # For compatibility with ergo-lib encoding, pass as flat hex list.
    var1_entries = ring.ring_commitments  # list of compressed-hex strings
    # We encode as Coll[Byte] array concatenated with length prefix per item.
    # Simple wire format: concatenate all 33-byte points prefixed by their count.
    num_members = len(var1_entries)
    # VLQ-encode count (single byte sufficient for ring sizes ≤ 127)
    count_byte = format(num_members, "02x")
    raw_points = "".join(var1_entries)  # each is 66 hex chars = 33 bytes
    var1 = "0c0c" + count_byte + raw_points

    return {"0": var0, "1": var1}


def verify_nullifier(nullifier_hex: str, blinding_factor: int) -> bool:
    """
    Verify that a nullifier was correctly computed as I = r·H.

    Used by auditors to verify withdrawal provenance when the depositor
    discloses their blinding factor r.

    Args:
        nullifier_hex: Compressed hex of the claimed nullifier I.
        blinding_factor: The depositor's blinding factor r.

    Returns:
        True if I == r·H, False otherwise.
    """
    try:
        nullifier_pt = decode_point(nullifier_hex)
        H = decode_point(NUMS_H)
        expected = blinding_factor * H
        return nullifier_pt.x() == expected.x() and nullifier_pt.y() == expected.y()
    except (ValueError, Exception):
        return False
