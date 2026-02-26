"""
ergo_agent.crypto — Cryptographic primitives for privacy protocols.

Provides:
- Pedersen Commitments (C = rG + amount·H)
- NUMS generator derivation via hash-to-curve
- DHTuple ring signature construction for withdrawals
- Range proofs for variable-amount splits
- Multi-asset Pedersen Commitments for Private OTC Swaps
- secp256k1 point encode/decode utilities
"""

from ergo_agent.crypto.dhtuple import (
    WithdrawalRing,
    build_withdrawal_ring,
    compute_nullifier,
    format_context_extension,
    generate_secondary_generator,
    verify_nullifier,
)
from ergo_agent.crypto.pedersen import (
    NUMS_H,
    G_COMPRESSED,
    PedersenCommitment,
    decode_point,
    encode_point,
    hash_to_curve,
)
from ergo_agent.crypto.range_proof import (
    RangeProof,
    BalanceProof,
    prove_range,
    verify_range,
    prove_balance,
    verify_balance,
)
from ergo_agent.crypto.multi_asset import (
    MultiAssetCommitment,
    derive_asset_generator,
    prove_multi_asset_balance,
    ERG_ASSET_ID,
)

__all__ = [
    # Pedersen
    "NUMS_H",
    "G_COMPRESSED",
    "PedersenCommitment",
    "decode_point",
    "encode_point",
    "hash_to_curve",
    # DHTuple
    "WithdrawalRing",
    "build_withdrawal_ring",
    "compute_nullifier",
    "format_context_extension",
    "generate_secondary_generator",
    "verify_nullifier",
    # Range Proofs
    "RangeProof",
    "BalanceProof",
    "prove_range",
    "verify_range",
    "prove_balance",
    "verify_balance",
    # Multi-Asset
    "MultiAssetCommitment",
    "derive_asset_generator",
    "prove_multi_asset_balance",
    "ERG_ASSET_ID",
]
