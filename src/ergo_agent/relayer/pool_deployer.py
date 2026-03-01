"""
Pool Deployer — Genesis pool creation and chaff deposit utilities.

Provides tools for:
- Deploying fresh MasterPoolBox instances with empty AVL trees
- Multi-tier pool configuration (10, 100, 1000 ERG)
- Genesis Lock threshold management
- Building chaff (dummy) deposits from the accumulator
"""

from __future__ import annotations

import hashlib
from typing import Any

from ergo_agent.relayer.deposit_relayer import (
    MIN_BOX_VALUE,
    DepositRelayer,
)

# ==============================================================================
# Constants
# ==============================================================================


# nanoERG per ERG
NANOERG = 1_000_000_000

# Pool tier configurations
POOL_TIERS: dict[str, dict[str, int]] = {
    "1_erg": {
        "denomination": 1 * NANOERG,
        "bounty": int(0.01 * NANOERG),    # 0.01 ERG bounty
    },
    "10_erg": {
        "denomination": 10 * NANOERG,
        "bounty": int(0.1 * NANOERG),     # 0.1 ERG bounty
    },
    "100_erg": {
        "denomination": 100 * NANOERG,
        "bounty": int(2.5 * NANOERG),     # 2.5 ERG bounty
    },
}


# Empty AVL Tree Sigma-serialized representation
# Type 0x64 (AvlTree) + 33-byte digest from AvlTreeProver(key_length=33) + flags(07)
# + keyLen(42=33 zigzag) + valueLen(00)
# The digest MUST match AvlTreeProver's initial state for proofs to verify on-chain.
EMPTY_AVL_TREE_HEX = (
    "64"
    + "befb05d26d04d4d4d1dc877f1ea2f879509a17191e5bd6e60ca98d3e3609a92500"
    + "07"               # Flags: insertions + removals + lookups
    + "2100"             # Key length: 33 (unsigned VLQ) + no value length (None)
)


# ==============================================================================
# Pool Deployer
# ==============================================================================


def build_genesis_pool_box(
    denomination: int,
    pool_ergo_tree: str,
) -> dict[str, Any]:
    """
    Create the initial MasterPoolBox output specification.

    The pool starts with:
    - R4: Empty Deposit AVL Tree
    - R5: Empty Nullifier AVL Tree
    - R6: Counter = 0
    - R7: denomination

    The pool is funded with MIN_BOX_VALUE (the deposits add ERG later).

    Args:
        denomination: Pool denomination in nanoERG.
        pool_ergo_tree: Compiled MasterPoolBox ErgoTree hex.

    Returns:
        Box output specification dict for transaction building.
    """
    return {
        "value": MIN_BOX_VALUE,
        "ergoTree": pool_ergo_tree,
        "assets": [],
        "additionalRegisters": {
            "R4": EMPTY_AVL_TREE_HEX,
            "R5": EMPTY_AVL_TREE_HEX,
            "R6": DepositRelayer._sigma_long(0),
            "R7": DepositRelayer._sigma_long(denomination),
        },
        "creationHeight": 0,
    }


def find_chaff_nonce(box_id_hex: str, max_attempts: int = 1000) -> tuple[str, str]:
    """
    Find a nonce such that blake2b256(box_id || nonce) is a valid secp256k1 x-coordinate.

    This mirrors the on-chain verification in PrivacyPoolChaffAccumulator.es:
        val expectedHash = blake2b256(chaffBox.id ++ nonce)
        val expectedBytes = Coll(2.toByte) ++ expectedHash
        val expectedCommitment = decodePoint(expectedBytes)

    The try-and-increment approach tests sequential 4-byte nonces until the
    resulting blake2b256 hash is a valid x-coordinate (i.e., x³+7 is a
    quadratic residue mod p). Statistically ~50% of random hashes are valid,
    so this terminates in 1-3 attempts on average.

    Args:
        box_id_hex: 64-char hex of the chaff output box ID.
        max_attempts: Maximum nonce values to try before giving up.

    Returns:
        Tuple of (commitment_hex, nonce_hex):
            - commitment_hex: 66-char compressed hex of the commitment point (0x02 prefix)
            - nonce_hex: hex string of the nonce bytes that produce a valid point

    Raises:
        RuntimeError: If no valid nonce is found within max_attempts.
    """
    from ergo_agent.crypto.pedersen import SECP256K1_P

    box_id_bytes = bytes.fromhex(box_id_hex)

    for i in range(max_attempts):
        # 4-byte big-endian nonce
        nonce_bytes = i.to_bytes(4, "big")
        digest = hashlib.blake2b(box_id_bytes + nonce_bytes, digest_size=32).digest()
        x = int.from_bytes(digest, "big")

        # x must be < p to be a valid field element
        if x >= SECP256K1_P:
            continue

        # Check if x³+7 is a quadratic residue (Euler criterion)
        y_sq = (pow(x, 3, SECP256K1_P) + 7) % SECP256K1_P
        if pow(y_sq, (SECP256K1_P - 1) // 2, SECP256K1_P) == 1:
            # Valid point — build compressed encoding with 0x02 (even y)
            commitment_hex = "02" + digest.hex()
            nonce_hex = nonce_bytes.hex()
            return commitment_hex, nonce_hex

    raise RuntimeError(
        f"find_chaff_nonce: no valid nonce found in {max_attempts} attempts "
        f"for box_id {box_id_hex[:16]}..."
    )


def build_chaff_commitment(box_id_hex: str, nonce_hex: str) -> str:
    """
    Generate a permanently unspendable Pedersen Commitment for a chaff deposit.

    Reconstructs the commitment exactly as the on-chain contract does:
        blake2b256(boxId ++ nonce) → 0x02 prefix → decodePoint

    The resulting point has no known discrete log (hash-to-curve NUMS property),
    making it permanently unspendable — no one can construct the DHTuple
    ring signature needed for withdrawal.

    Args:
        box_id_hex: 64-char hex of the chaff output box ID.
        nonce_hex: Hex string of the nonce that produces a valid curve point.

    Returns:
        66-char compressed hex of the chaff commitment point (0x02 prefix).

    Raises:
        ValueError: If the nonce does not produce a valid curve point.
    """
    from ergo_agent.crypto.pedersen import SECP256K1_P

    box_id_bytes = bytes.fromhex(box_id_hex)
    nonce_bytes = bytes.fromhex(nonce_hex)
    digest = hashlib.blake2b(box_id_bytes + nonce_bytes, digest_size=32).digest()
    x = int.from_bytes(digest, "big")

    if x >= SECP256K1_P:
        raise ValueError(
            "Nonce produces x >= p (not a valid field element)"
        )

    y_sq = (pow(x, 3, SECP256K1_P) + 7) % SECP256K1_P
    if pow(y_sq, (SECP256K1_P - 1) // 2, SECP256K1_P) != 1:
        raise ValueError(
            "Nonce does not produce a valid curve point (x³+7 is not a QR)"
        )

    return "02" + digest.hex()


def build_chaff_intent(
    accumulator_box_id: str,
    denomination: int,
    intent_ergo_tree: str,
    chaff_box_id_hex: str | None = None,
) -> dict[str, Any]:
    """
    Build a chaff IntentToDeposit output from the accumulator.

    If chaff_box_id_hex is provided, the nonce is computed deterministically
    via find_chaff_nonce and included in the context extension. If not provided,
    a placeholder commitment is used (for pre-construction before the box ID
    is known — the caller must finalize after transaction building).

    Args:
        accumulator_box_id: Box ID of the chaff accumulator being spent.
        denomination: Pool denomination in nanoERG.
        intent_ergo_tree: Compiled IntentToDeposit ErgoTree hex.
        chaff_box_id_hex: Optional 64-char hex of the chaff output box ID.
            When known, enables deterministic nonce computation.

    Returns:
        Box output specification dict for the chaff intent box.
        Includes 'contextExtension' with nonce when chaff_box_id_hex is provided.
    """
    result: dict[str, Any] = {
        "value": denomination,
        "ergoTree": intent_ergo_tree,
        "assets": [],
        "additionalRegisters": {},
        "creationHeight": 0,
    }

    if chaff_box_id_hex is not None:
        commitment_hex, nonce_hex = find_chaff_nonce(chaff_box_id_hex)
        result["additionalRegisters"]["R4"] = "07" + commitment_hex
        result["contextExtension"] = {"0": nonce_hex}
    else:
        # Placeholder — caller must finalize with the actual box ID
        # Use a dummy commitment derived from the accumulator box ID
        commitment_hex, nonce_hex = find_chaff_nonce(accumulator_box_id)
        result["additionalRegisters"]["R4"] = "07" + commitment_hex
        result["contextExtension"] = {"0": nonce_hex}

    return result





def get_tier_config(tier_name: str) -> dict[str, int]:
    """
    Get the configuration for a specific pool tier.

    Args:
        tier_name: One of '10_erg', '100_erg', '1000_erg'.

    Returns:
        Dict with 'denomination' and 'bounty' keys (values in nanoERG).

    Raises:
        ValueError: If tier_name is not recognized.
    """
    if tier_name not in POOL_TIERS:
        raise ValueError(
            f"Unknown tier: {tier_name}. Available: {list(POOL_TIERS.keys())}"
        )
    return POOL_TIERS[tier_name]
