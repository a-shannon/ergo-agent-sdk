"""
Multi-Asset Pedersen Commitments for Private OTC Swaps.

Extends the single-asset Pedersen scheme to support multiple asset types
within a single commitment using deterministic per-asset NUMS generators.

Architecture:
    For a commitment over N asset types:
        C = r·G + v_erg·H_erg + v_tok1·H_tok1 + v_tok2·H_tok2 + ...

    Each generator H_i is derived via a deterministic hash-to-curve chain:
        H_erg  = hash_to_curve(G_compressed)        [same as existing NUMS_H]
        H_tok1 = hash_to_curve(H_erg_compressed)
        H_tok2 = hash_to_curve(H_tok1_compressed)  [not used — see below]

    Actually, to support arbitrary asset IDs (Ergo token IDs are 64-char hex),
    we derive each generator from the asset ID directly:
        H_asset = hash_to_curve(Blake2b256(G_compressed || asset_id_bytes))

    This ensures:
    - Each asset gets a unique, NUMS generator
    - No relationship between generators (prevents cross-asset forging)
    - Deterministic: same asset ID always maps to the same generator

References:
    [Grin]  MimbleWimble/Grin multi-asset extension (RFC-0003),
            adapted for Ergo's token model with domain-separated generators.
    [Ped91] T.P. Pedersen, CRYPTO '91, §3.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from ergo_agent.crypto.pedersen import (
    G_COMPRESSED,
    NUMS_H,
    SECP256K1_N,
    SECP256K1_P,
    decode_point,
    encode_point,
    hash_to_curve,
    _GENERATOR,
    _H_POINT,
)


# ==============================================================================
# Constants
# ==============================================================================

# The "ERG" asset uses the existing NUMS_H as its generator
ERG_ASSET_ID = "erg"
"""Special asset ID for native ERG — uses the standard NUMS generator."""


# ==============================================================================
# Per-Asset Generator Derivation
# ==============================================================================


@lru_cache(maxsize=256)
def derive_asset_generator(asset_id: str) -> str:
    """
    Derive a NUMS generator for a specific asset ID.

    For ERG, returns the standard NUMS_H. For tokens, derives a unique
    generator via hash_to_curve on Blake2b256(G || asset_id).

    Args:
        asset_id: The asset identifier. Use 'erg' for native ERG,
                  or the 64-char token ID hex for Ergo tokens.

    Returns:
        66-char compressed hex of the asset-specific NUMS generator.
    """
    if asset_id == ERG_ASSET_ID:
        return NUMS_H

    # Derive a seed: Blake2b256(G_compressed || asset_id_bytes)
    hasher = hashlib.blake2b(digest_size=32)
    hasher.update(bytes.fromhex(G_COMPRESSED))
    hasher.update(asset_id.encode("utf-8"))
    seed_hex = "02" + hasher.hexdigest()  # Use as a compressed point seed

    # Use hash_to_curve on this seed to get a valid point
    return hash_to_curve(seed_hex)


# ==============================================================================
# Multi-Asset Commitment
# ==============================================================================


class MultiAssetCommitment:
    """
    Multi-asset Pedersen Commitment scheme.

    Commits to multiple asset amounts in a single elliptic curve point:
        C = r·G + Σ(v_i · H_i)

    where each H_i is derived from the asset ID via derive_asset_generator.

    Usage:
        C = MultiAssetCommitment.commit(r, {"erg": 100_000_000_000, "token_abc": 50})
        ok = MultiAssetCommitment.verify(C, r, {"erg": 100_000_000_000, "token_abc": 50})
    """

    @staticmethod
    def commit(
        blinding_factor: int,
        amounts: dict[str, int],
    ) -> str:
        """
        Create a multi-asset Pedersen Commitment.

            C = r·G + v_erg·H_erg + v_tok1·H_tok1 + ...

        Args:
            blinding_factor: Random blinding factor r in [1, N-1].
            amounts: Dict mapping asset_id → amount. All amounts must be ≥ 0.

        Returns:
            66-char compressed hex of the commitment point C.

        Raises:
            ValueError: If blinding_factor is out of range, amounts are negative,
                        or no assets are specified.
        """
        if blinding_factor <= 0 or blinding_factor >= SECP256K1_N:
            raise ValueError("Blinding factor must be in [1, N-1]")
        if not amounts:
            raise ValueError("Must commit to at least one asset")
        if any(v < 0 for v in amounts.values()):
            raise ValueError("All amounts must be non-negative")

        # Start with r·G
        C = blinding_factor * _GENERATOR

        # Add v_i · H_i for each asset
        for asset_id, amount in sorted(amounts.items()):
            if amount == 0:
                continue
            H_i_hex = derive_asset_generator(asset_id)
            H_i = decode_point(H_i_hex)
            C = C + (amount * H_i)

        return encode_point(C)

    @staticmethod
    def verify(
        commitment_hex: str,
        blinding_factor: int,
        amounts: dict[str, int],
    ) -> bool:
        """
        Verify a multi-asset Pedersen Commitment.

        Checks: C == r·G + Σ(v_i · H_i)

        Args:
            commitment_hex: 66-char compressed hex of commitment C.
            blinding_factor: The blinding factor r.
            amounts: Dict mapping asset_id → amount.

        Returns:
            True if the commitment matches, False otherwise.
        """
        try:
            expected = MultiAssetCommitment.commit(blinding_factor, amounts)
            return expected == commitment_hex
        except (ValueError, Exception):
            return False

    @staticmethod
    def open_single_asset(
        commitment_hex: str,
        amounts: dict[str, int],
        target_asset: str,
    ) -> str:
        """
        Open a commitment by subtracting all known asset amounts except one.

        Returns the residual point, which for a valid commitment equals
        r·G + v_target·H_target. This enables selective disclosure.

        Args:
            commitment_hex: 66-char compressed hex of commitment C.
            amounts: Dict of known asset amounts (excluding target).
            target_asset: The asset to leave unrevealed.

        Returns:
            66-char compressed hex of residual point.
        """
        C = decode_point(commitment_hex)

        # Subtract known asset components
        for asset_id, amount in sorted(amounts.items()):
            if asset_id == target_asset or amount == 0:
                continue
            H_i = decode_point(derive_asset_generator(asset_id))
            C = C + ((-amount) * H_i)

        return encode_point(C)


# ==============================================================================
# Multi-Asset Balance Proof
# ==============================================================================


def prove_multi_asset_balance(
    input_blindings: list[int],
    input_amounts: list[dict[str, int]],
    output_blindings: list[int],
    output_amounts: list[dict[str, int]],
) -> dict[str, Any]:
    """
    Prove value conservation across multiple assets in a shielded transfer.

    For each asset, the sum of inputs must equal the sum of outputs.
    The residual D = Σ C_in - Σ C_out = Δr · G (pure G-multiple).

    Args:
        input_blindings: Blinding factors for input commitments.
        input_amounts: List of {asset_id: amount} dicts for inputs.
        output_blindings: Blinding factors for output commitments.
        output_amounts: List of {asset_id: amount} dicts for outputs.

    Returns:
        Dict with input_commitments, output_commitments, residual, delta_r.

    Raises:
        ValueError: If any asset doesn't balance across inputs/outputs.
    """
    # Collect all asset IDs
    all_assets: set[str] = set()
    for a in input_amounts + output_amounts:
        all_assets.update(a.keys())

    # Verify each asset balances
    for asset in sorted(all_assets):
        sum_in = sum(a.get(asset, 0) for a in input_amounts)
        sum_out = sum(a.get(asset, 0) for a in output_amounts)
        if sum_in != sum_out:
            raise ValueError(
                f"Asset '{asset}' doesn't balance: {sum_in} ≠ {sum_out}"
            )

    # Create commitments
    input_cs = [
        MultiAssetCommitment.commit(r, amounts)
        for r, amounts in zip(input_blindings, input_amounts)
    ]
    output_cs = [
        MultiAssetCommitment.commit(r, amounts)
        for r, amounts in zip(output_blindings, output_amounts)
    ]

    # Compute residual
    sum_in_pt = None
    for c_hex in input_cs:
        pt = decode_point(c_hex)
        sum_in_pt = pt if sum_in_pt is None else sum_in_pt + pt

    sum_out_pt = None
    for c_hex in output_cs:
        pt = decode_point(c_hex)
        sum_out_pt = pt if sum_out_pt is None else sum_out_pt + pt

    D = sum_in_pt + (-1 * sum_out_pt)
    delta_r = (sum(input_blindings) - sum(output_blindings)) % SECP256K1_N

    return {
        "input_commitments": input_cs,
        "output_commitments": output_cs,
        "residual_hex": encode_point(D),
        "delta_r": delta_r,
        "assets_proven": sorted(all_assets),
    }
