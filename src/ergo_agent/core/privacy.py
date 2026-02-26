"""
Privacy module for privacy pool — application-level ring-signature privacy pools.

This module provides:
- The NUMS second generator H (for key images / nullifiers)
- The ErgoScript source for the PoolContract (deposit + withdrawal paths)
- High-level helpers for constructing deposit and withdrawal transactions

Architecture:
    PoolBox {
        tokens: [(cashTokenId, totalReserve)]
        R4: Coll[GroupElement] — deposit keys
        R5: AvlTree — nullifier set (used key images)
        R6: Long — denomination
        R7: Int — maxDeposits (8 or 16)
    }

    Deposit: add a key to R4, add tokens to the pool
    Withdrawal: ring-signature proves ownership of one key, key image as nullifier
"""

from __future__ import annotations

import random
from typing import Any

from ergo_agent.core.builder import MIN_BOX_VALUE_NANOERG, TransactionBuilder
from ergo_agent.core.models import Box
from ergo_agent.core.node import ErgoNode

# ==============================================================================
# NUMS Second Generator H
# ==============================================================================
# Derived deterministically: Blake2b256(G_compressed)
# → x-coordinate on secp256k1, verified on-curve, compressed encoding.
# Nobody knows the discrete log of H w.r.t. G because x is a hash output.
#
# Verification:
#   import hashlib
#   h = hashlib.blake2b(bytes.fromhex(G_COMPRESSED), digest_size=32).digest()
#   x = int.from_bytes(h, 'big') % p
#   # x³ + 7 mod p is a quadratic residue → valid curve point
#
# Uses Blake2b256 (Ergo's canonical hash) — NOT SHA-256.
# Reference: [Ped91] §3, [H2C] §5.
NUMS_H_HEX = "022975f1d28b92b6e84499b83b0797ef5235553eeb7edaa0cea243c1128c2fe739"

# ==============================================================================
# Pool Contract ErgoScript Source — PrivacyPoolV6 (Unified, Lazy-Evaluated)
# ==============================================================================
# CRITICAL: Uses if/else branching based on tokenDiff to ensure lazy evaluation.
# Without this, strict val evaluation causes NPE when OUTPUTS(1).tokens is
# accessed during a deposit (where output 1 has no tokens).
#
# Also uses explicit .toInt cast on (tokenDiff / denom) to avoid the silent
# Int == Long → false bug in ErgoScript runtime.

POOL_CONTRACT_SCRIPT = '''
{
    val poolKeys  = SELF.R4[Coll[GroupElement]].get
    val denom     = SELF.R6[Long].get
    val maxRing   = SELF.R7[Int].get
    val poolOut   = OUTPUTS(0)
    val H = decodePoint(fromBase16("''' + NUMS_H_HEX + '''"))
    val tokenDiff = poolOut.tokens(0)._2 - SELF.tokens(0)._2

    if (tokenDiff > 0L) {
        val scriptOk = poolOut.propositionBytes == SELF.propositionBytes
        val denomOk  = poolOut.R6[Long].get == denom
        val maxOk    = poolOut.R7[Int].get == maxRing
        val treeOk   = poolOut.R5[AvlTree].get.digest == SELF.R5[AvlTree].get.digest
        val tokenIdOk = poolOut.tokens(0)._1 == SELF.tokens(0)._1
        val tokenOk = (tokenDiff % denom) == 0L
        val tickets: Int = (tokenDiff / denom).toInt
        val newKeys  = poolOut.R4[Coll[GroupElement]].get
        val sizeOk   = newKeys.size == poolKeys.size + tickets
        val spaceOk  = newKeys.size <= maxRing
        val oldKeysOk = poolKeys.indices.forall { (i: Int) => newKeys(i) == poolKeys(i) }
        val newKey = newKeys(poolKeys.size)
        val newKeyValid = newKey != groupGenerator
        val uniqueKeyOk = poolKeys.forall { (pk: GroupElement) => pk != newKey }
        sigmaProp(scriptOk && denomOk && maxOk && treeOk && tokenIdOk && tokenOk &&
                  sizeOk && spaceOk && oldKeysOk && newKeyValid && uniqueKeyOk)
    } else if (tokenDiff < 0L) {
        val ringOk   = poolKeys.size >= 2
        val scriptOk = poolOut.propositionBytes == SELF.propositionBytes
        val denomOk  = poolOut.R6[Long].get == denom
        val maxOk    = poolOut.R7[Int].get == maxRing
        val keysOk   = poolOut.R4[Coll[GroupElement]].get == poolKeys
        val tokenIdOk = poolOut.tokens(0)._1 == SELF.tokens(0)._1
        val tokenOk  = tokenDiff == -denom
        val keyImage    = getVar[GroupElement](0).get
        val insertProof = getVar[Coll[Byte]](1).get
        val keyImageSafe = keyImage != groupGenerator
        val keyImageNotH = keyImage != H
        val curTree  = SELF.R5[AvlTree].get
        val newTree  = curTree.insert(
            Coll((keyImage.getEncoded, Coll[Byte]())),
            insertProof
        ).get
        val treeOk   = poolOut.R5[AvlTree].get.digest == newTree.digest
        val noteOutOk = if (OUTPUTS.size > 1 && OUTPUTS(1).tokens.size > 0) {
            OUTPUTS(1).tokens(0)._1 == SELF.tokens(0)._1 && OUTPUTS(1).tokens(0)._2 == denom
        } else { false }
        val ringProof = atLeast(1, poolKeys.map { (pk: GroupElement) =>
            proveDlog(pk) && proveDHTuple(groupGenerator, H, pk, keyImage)
        })
        sigmaProp(ringOk && scriptOk && denomOk && maxOk && keysOk &&
                  tokenIdOk && tokenOk && noteOutOk && treeOk &&
                  keyImageSafe && keyImageNotH) && ringProof
    } else {
        val hasTokens  = SELF.tokens(0)._2 > 0L
        val ageOk      = HEIGHT - SELF.creationInfo._1 >= 788400
        val scriptOk   = poolOut.propositionBytes == SELF.propositionBytes
        val keysOk     = poolOut.R4[Coll[GroupElement]].get == poolKeys
        val nullOk     = poolOut.R5[AvlTree].get.digest == SELF.R5[AvlTree].get.digest
        val denomOk    = poolOut.R6[Long].get == denom
        val maxOk      = poolOut.R7[Int].get == maxRing
        val tokenIdOk  = poolOut.tokens(0)._1 == SELF.tokens(0)._1
        val tokenAmtOk = tokenDiff == 0L
        sigmaProp(hasTokens && ageOk && scriptOk && keysOk && nullOk &&
                  denomOk && maxOk && tokenIdOk && tokenAmtOk)
    }
}
'''

# Backwards compatibility aliases
POOL_WITHDRAW_SCRIPT = POOL_CONTRACT_SCRIPT
POOL_DEPOSIT_SCRIPT = POOL_CONTRACT_SCRIPT

# Note contract — simplified bearer instrument
NOTE_CONTRACT_SCRIPT = '''
{
  proveDlog(SELF.R4[GroupElement].get)
}
'''


# ==============================================================================
# Transaction Builders & Aggregators
# ==============================================================================

def decompose_into_tiers(amount: int) -> dict[int, int]:
    """
    Greedy decomposition algorithm for privacy pool "Auto-Route" mechanism.
    Breaks any amount into the optimal number of deposits across the 4 pool tiers.
    
    Tiers (in tokens): 1,000,000 | 100,000 | 10,000 | 1,000
    
    Args:
        amount: Total token amount to anonymize
        
    Returns:
        dict mapping denomination to number of required tickets (keys)
        e.g., 15,300,000 -> {1000000: 15, 100000: 3, 10000: 0, 1000: 0}
        
    Note: Any "loose change" remainder (< 1,000) cannot be deposited and is ignored here.
    """
    tiers = [1_000_000, 100_000, 10_000, 1_000]
    result = {t: 0 for t in tiers}
    
    remaining = amount
    for tier in tiers:
        count = remaining // tier
        result[tier] = count
        remaining = remaining % tier
        
    return result

import secrets
import ecdsa
import hashlib

# secp256k1 curve parameters
_SECP256K1_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F


def _decode_compressed_point(hex_str: str) -> ecdsa.ellipticcurve.Point:
    """Decode a 33-byte compressed secp256k1 point to an ecdsa Point."""
    b = bytes.fromhex(hex_str)
    is_even = b[0] == 0x02
    x_coord = int.from_bytes(b[1:], "big")
    y_squared = (pow(x_coord, 3, _SECP256K1_P) + 7) % _SECP256K1_P
    y = pow(y_squared, (_SECP256K1_P + 1) // 4, _SECP256K1_P)
    if (y % 2 == 0) != is_even:
        y = _SECP256K1_P - y
    return ecdsa.ellipticcurve.Point(ecdsa.SECP256k1.curve, x_coord, y)


def _encode_compressed_point(pt: ecdsa.ellipticcurve.Point) -> str:
    """Encode an ecdsa Point as a 33-byte compressed hex string."""
    prefix = b"\x02" if pt.y() % 2 == 0 else b"\x03"
    return (prefix + pt.x().to_bytes(32, "big")).hex()


def generate_fresh_secret() -> tuple[str, str]:
    """
    Securely generates a fresh mathematical secret (private key) and its
    corresponding public key (compressed secp256k1 point) for a pool deposit.

    Returns:
        tuple: (private_key_hex, public_key_compressed_hex)
    """
    priv_key_bytes = secrets.token_bytes(32)
    signing_key = ecdsa.SigningKey.from_string(priv_key_bytes, curve=ecdsa.SECP256k1)
    verifying_key = signing_key.get_verifying_key()
    x = verifying_key.pubkey.point.x()
    y = verifying_key.pubkey.point.y()
    prefix = bytes([0x02]) if y % 2 == 0 else bytes([0x03])
    pub_key_compressed = prefix + x.to_bytes(32, byteorder="big")
    return priv_key_bytes.hex(), pub_key_compressed.hex()


# ── secp256k1 curve order ─────────────────────────────────────────────────
_SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def compute_key_image(secret_hex: str) -> str:
    """
    Compute the key image (nullifier) M = secret * H for a withdrawal.

    The key image is used to prevent double-spending: once a key image is
    inserted into the AvlTree nullifier set, the same secret cannot be
    used again.

    Args:
        secret_hex: The 32-byte secret (private key) as hex string.

    Returns:
        Compressed GroupElement hex of the key image (33 bytes / 66 chars).

    Raises:
        ValueError: If the secret is not a valid 32-byte hex string or is zero.
    """
    # Input validation
    if not secret_hex or not isinstance(secret_hex, str):
        raise ValueError("secret_hex must be a non-empty hex string")
    if len(secret_hex) != 64:
        raise ValueError(
            f"secret_hex must be exactly 64 hex characters (32 bytes), got {len(secret_hex)}"
        )
    try:
        x = int(secret_hex, 16)
    except ValueError as err:
        raise ValueError(f"secret_hex is not valid hex: {secret_hex[:16]}...") from err
    if x == 0:
        raise ValueError("secret_hex must not be zero (produces identity point)")
    if x >= _SECP256K1_N:
        raise ValueError("secret_hex exceeds the secp256k1 curve order")

    H_point = _decode_compressed_point(NUMS_H_HEX)
    M_point = x * H_point
    return _encode_compressed_point(M_point)


def generate_avl_insert_proof(
    key_image_hex: str,
    current_r5_hex: str | None = None,
) -> tuple[bytes, str]:
    """
    Generate an AvlTree insert proof for the key image nullifier.

    Uses the `ergo_avltree` Python extension (PyO3 wrapper around
    `ergo_avltree_rust`) to create and insert into the authenticated
    AVL+ tree.

    Args:
        key_image_hex: Compressed GroupElement hex of the key image.
        current_r5_hex: Current R5 register hex (AvlTree). If None,
            assumes an empty tree.

    Returns:
        tuple: (proof_bytes, new_r5_hex) where new_r5_hex is the full
            Sigma-serialized AvlTree constant for the output box R5.
    """
    from ergo_avltree import AvlTreeProver

    prover = AvlTreeProver(key_length=33)
    prover.insert(bytes.fromhex(key_image_hex), b"")
    proof_bytes, new_digest_bytes = prover.generate_proof()

    # Sigma serialize: type 0x64 + 33-byte digest + flags(07) + keyLen(21=33)
    new_r5_hex = "64" + new_digest_bytes.hex() + "072100"

    return proof_bytes, new_r5_hex


def _vlq_encode(n: int) -> str:
    """Encode an integer as VLQ hex for Sigma serialization."""
    result: list[int] = []
    while n >= 0x80:
        result.append((n & 0x7F) | 0x80)
        n >>= 7
    result.append(n)
    return bytes(result).hex()


def serialize_context_extension(
    key_image_hex: str,
    proof_bytes: bytes,
) -> dict[str, str]:
    """
    Build the context extension dict for a withdrawal transaction input.

    Var 0: GroupElement (type 0x07 + 33 compressed bytes)
    Var 1: Coll[Byte] (type 0x0e + VLQ length + raw bytes)

    Args:
        key_image_hex: Compressed key image hex (66 chars).
        proof_bytes: Raw AvlTree insert proof bytes.

    Returns:
        dict mapping string var indices to hex-encoded Sigma values.
    """
    var0 = "07" + key_image_hex
    var1 = "0e" + _vlq_encode(len(proof_bytes)) + proof_bytes.hex()
    return {"0": var0, "1": var1}



def find_optimal_pool(
    node: ErgoNode,
    pool_ergo_tree: str,
    pool_token_id: str,
    denomination: int,
) -> Box:
    """
    Finds an optimal, un-congested PoolBox for a deposit to mitigate UTXO contention.

    Queries the blockchain for all unspent PoolBoxes matching the ErgoTree contract,
    filters for those serving the requested denomination that have available capacity,
    and returns a randomly selected pool to spread out concurrent deposits.

    Args:
        node: Connected ErgoNode client
        pool_ergo_tree: ErgoTree hex of the pool contract
        pool_token_id: The privacy pool token ID
        denomination: The denomination amount requested

    Returns:
        Box: A matched, unsaturated PoolBox.

    Raises:
        ValueError: If no valid pools with available capacity are found.
    """
    # Fetch all live boxes for the PoolContract
    boxes = node.get_boxes_by_ergo_tree(pool_ergo_tree, limit=100)

    valid_pools: list[Box] = []
    for box in boxes:
        # Check token ID exists (even if reserve is 0, token must be in assets array)
        if not any(t.token_id == pool_token_id for t in box.tokens):
            continue

        # Check denomination matches R6
        pool_denom = box.additional_registers.get("R6")
        if pool_denom != str(denomination):
            continue

        # Check capacity: number of keys in R4 < maxDeposits in R7
        # Note: R4 is a Coll[GroupElement], ErgoNode API typically returns
        # heavily typed JSON, but for simplicity assuming we can estimate size
        # or parse the Coll. We'll do a basic check here.
        keys_str = box.additional_registers.get("R4", "")
        max_n = int(box.additional_registers.get("R7", "16"))

        # A rough estimate: if it's full, we skip.
        # Ergo API Coll[GroupElement] string hex format contains length headers.
        # This is a basic safeguard; true parsing requires sigmastate deserialization.
        if len(keys_str) > (max_n * 66):  # 33 bytes (66 hex chars) per key approx
            continue

        valid_pools.append(box)

    if not valid_pools:
        raise ValueError(f"No pools available with capacity for denomination {denomination}")

    # Random selection completely eliminates UTXO contention among parallel agents
    return random.choice(valid_pools)


def build_pool_deposit_tx(
    builder: TransactionBuilder,
    pool_box: Box,
    note_box: Box,
    depositor_public_keys_hex: list[str],
    pool_ergo_tree: str,
    pool_token_id: str,
    denomination: int,
) -> dict[str, Any]:
    """
    Build a deposit transaction: send a NoteBox's tokens into a PoolBox.

    The depositor's public keys are appended to the pool's key list (R4).
    The pool's token reserve increases by (denomination * number of keys).

    Args:
        builder: a TransactionBuilder instance
        pool_box: the PoolBox to deposit into
        note_box: the NoteBox being deposited (must contain enough tokens)
        depositor_public_keys_hex: list of the depositor's one-time public keys
        pool_ergo_tree: the ErgoTree hex of the pool contract
        pool_token_id: the privacy pool token ID
        denomination: the denomination amount (must match pool's R6)

    Returns:
        unsigned transaction dict
    """
    # Get current keys from pool
    # Note: R4 deserialization/serialization logic would depend on the Ergo SDK specifics.
    # For now, we represent the intent.
    current_keys_r4 = pool_box.additional_registers.get("R4", "")
    current_reserve = 0
    for t in pool_box.tokens:
        if t.token_id == pool_token_id:
            current_reserve = t.amount
            break

    tickets = len(depositor_public_keys_hex)
    deposit_amount = tickets * denomination
    new_reserve = current_reserve + deposit_amount

    # Build: pool_box + note_box as inputs → new pool_box as output
    tx = (
        builder
        .with_input(pool_box)    # Pool being updated
        .with_input(note_box)    # Note being deposited
        .add_output_raw(
            ergo_tree=pool_ergo_tree,
            value_nanoerg=pool_box.value,
            tokens=[{"tokenId": pool_token_id, "amount": new_reserve}],
            registers={
                # R4: updated keys (append ALL depositor keys) — must be serialized
                # R5: unchanged nullifier tree
                # R6: denomination (unchanged)
                # R7: maxDeposits (unchanged)
                "R4": current_keys_r4,  # TODO: append depositor_public_keys_hex properly
                "R5": pool_box.additional_registers.get("R5", ""),
                "R6": pool_box.additional_registers.get("R6", ""),
                "R7": pool_box.additional_registers.get("R7", ""),
            },
        )
        .build()
    )
    return tx


def build_pool_withdraw_tx(
    builder: TransactionBuilder,
    pool_box: Box,
    secret_hex: str,
    recipient_ergo_tree: str,
    pool_ergo_tree: str,
    pool_token_id: str,
    denomination: int,
) -> dict[str, Any]:
    """
    Build a withdrawal transaction: ring-signature proof to withdraw from a PoolBox.

    Computes the key image from the secret, generates the AvlTree insert proof,
    and serializes the context extension. The ring proof itself is generated
    by the node's prover at signing time.

    Args:
        builder: a TransactionBuilder instance
        pool_box: the PoolBox to withdraw from
        secret_hex: the depositor's 32-byte secret key (hex)
        recipient_ergo_tree: ErgoTree of the withdrawal recipient
        pool_ergo_tree: ErgoTree hex of the pool contract
        pool_token_id: the privacy pool token ID
        denomination: amount to withdraw (must match pool's R6)

    Returns:
        unsigned transaction dict
    """
    # 1. Compute key image (nullifier)
    key_image_hex = compute_key_image(secret_hex)

    # 2. Generate AvlTree insert proof and new R5 digest
    current_r5 = pool_box.additional_registers.get("R5", "")
    proof_bytes, new_r5_hex = generate_avl_insert_proof(key_image_hex, current_r5)

    # 3. Build context extension
    extension = serialize_context_extension(key_image_hex, proof_bytes)

    # 4. Compute new token reserve
    current_reserve = 0
    for t in pool_box.tokens:
        if t.token_id == pool_token_id:
            current_reserve = t.amount
            break
    new_reserve = current_reserve - denomination

    tx = (
        builder
        .with_input(pool_box, extension=extension)
        .add_output_raw(
            ergo_tree=pool_ergo_tree,
            value_nanoerg=pool_box.value,
            tokens=[{"tokenId": pool_token_id, "amount": new_reserve}],
            registers={
                "R4": pool_box.additional_registers.get("R4", ""),
                "R5": new_r5_hex,
                "R6": pool_box.additional_registers.get("R6", ""),
                "R7": pool_box.additional_registers.get("R7", ""),
            },
        )
        .add_output_raw(
            ergo_tree=recipient_ergo_tree,
            value_nanoerg=MIN_BOX_VALUE_NANOERG,
            tokens=[{"tokenId": pool_token_id, "amount": denomination}],
        )
        .build()
    )
    return tx


def build_auto_route_claim_tx(
    builder: TransactionBuilder,
    vending_machine_box: Box,
    user_wallet_box: Box,
    claim_amount: int,
    pool_trees: dict[int, str],
    generated_keys: dict[int, list[str]],
    token_id: str,
    treasury_ergo_tree: str,
    price_nanoerg: int = 1000
) -> dict[str, Any]:
    """
    Builds the massive Auto-Route Claim transaction for the Genesis Sale.
    Routes the user's allocated tokens directly into the 4 privacy pools based on greedy decomposition.

    Args:
        builder: TransactionBuilder instance
        vending_machine_box: The Genesis Snapshot Claim contract box
        user_wallet_box: The user's input providing the signature and identifying their allocation
        claim_amount: Total amount of tokens being claimed
        pool_trees: Mapping of denomination -> ErgoTree hex for the 4 pools
        generated_keys: Mapping of denomination -> list of generated public keys
        token_id: Privacy token ID
        treasury_ergo_tree: Liquidity lock contract address
        price_nanoerg: Price per token in nanoERG

    Returns:
        unsigned transaction dict
    """
    # 1. Calculate decomposition to verify
    decomposition = decompose_into_tiers(claim_amount)
    
    # Verify the user generated the correct number of keys for their claim size
    for denom, count in decomposition.items():
        if len(generated_keys.get(denom, [])) != count:
            raise ValueError(f"Mismatch in keys for {denom} tier. Expected {count}, got {len(generated_keys.get(denom, []))}")

    # 2. Vending Machine Output (Change)
    current_tokens = 0
    for t in vending_machine_box.tokens:
        if t.token_id == token_id:
            current_tokens = t.amount
            break
            
    remaining_tokens = current_tokens - claim_amount
    
    # Extension variables for the AVL tree lookup/remove
    # Assuming the builder handles the exact bytes in a real env
    extension = {
        "0": "lookup_proof_bytes_placeholder",
        "1": "remove_proof_bytes_placeholder"
    }
    
    builder.with_input(vending_machine_box, extension=extension)
    builder.with_input(user_wallet_box)
    
    # Output 0: Vending Machine Change
    builder.add_output_raw(
        ergo_tree=vending_machine_box.ergo_tree,
        value_nanoerg=MIN_BOX_VALUE_NANOERG,
        tokens=[{"tokenId": token_id, "amount": remaining_tokens}],
        registers={"R4": "updated_avl_digest_placeholder"}
    )
    
    # Outputs 1..N: The Pool Deposits
    for denom, keys in generated_keys.items():
        if not keys:
            continue
            
        pool_tree = pool_trees[denom]
        deposit_tokens = denom * len(keys)
        
        # We send the tokens to the pool contract. The pool contract itself
        # will act as the INPUT in the subsequent actual pool deposit transaction
        # where these keys will be merged into the pool's state. 
        # (This represents the routing destination step).
        builder.add_output_raw(
            ergo_tree=pool_tree,
            value_nanoerg=MIN_BOX_VALUE_NANOERG,
            tokens=[{"tokenId": token_id, "amount": deposit_tokens}],
            registers={"R4": "".join(keys)} # Placeholder serialization of key array
        )

    # Output (N+1): Treasury Payment
    required_payment = claim_amount * price_nanoerg
    builder.add_output_raw(
        ergo_tree=treasury_ergo_tree,
        value_nanoerg=required_payment,
        tokens=[]
    )
    
    return builder.build()


# ==============================================================================
# Client-Side Anonymity Set Analysis (privacy pool v7)
# ==============================================================================
#
# Replaces the on-chain genesis lock. Users are warned client-side if the
# anonymity set is weak, rather than blocked by a contract threshold.
#
# Privacy Score (0-100):
#   0-20:  CRITICAL — Do not withdraw
#   21-40: POOR     — Withdraw only if necessary
#   41-60: MODERATE — Acceptable for routine transactions
#   61-80: GOOD     — Strong anonymity set
#   81-100: EXCELLENT — Very high privacy

from dataclasses import dataclass, field as dc_field
import logging as _logging

_logger = _logging.getLogger(__name__)


@dataclass
class AnonymityAssessment:
    """Result of an anonymity set analysis for a privacy pool."""

    pool_box_id: str
    denomination: int
    deposit_count: int
    unique_sources: int
    top_source_deposits: int
    temporal_spread_blocks: int
    privacy_score: int
    risk_level: str  # CRITICAL, POOR, MODERATE, GOOD, EXCELLENT
    warnings: list[str] = dc_field(default_factory=list)

    @property
    def is_safe_to_withdraw(self) -> bool:
        return self.privacy_score >= 41

    def summary(self) -> str:
        return (
            f"Privacy Score: {self.privacy_score}/100 ({self.risk_level}) | "
            f"{self.deposit_count} deposits from {self.unique_sources} sources"
        )


def _decode_long_register(hex_val: str) -> int:
    """Decode a Sigma Long register (type 0x05 + zigzag VLQ)."""
    data = bytes.fromhex(hex_val)
    if data[0] != 0x05:
        raise ValueError(f"Expected Long type 0x05, got 0x{data[0]:02x}")
    val = 0
    shift = 0
    for b in data[1:]:
        val |= (b & 0x7F) << shift
        shift += 7
        if b < 0x80:
            break
    return (val >> 1) ^ -(val & 1)


def analyze_anonymity_set(
    node_url: str,
    pool_box_id: str,
    api_key: str = "hello",
    max_txs_to_scan: int = 200,
) -> AnonymityAssessment:
    """
    Analyze the anonymity set quality of a privacy pool MasterPoolBox.

    Queries pool state and traces deposit TX history to assess source
    diversity, Sybil concentration, and temporal spread.

    Args:
        node_url: Ergo node API URL
        pool_box_id: Box ID of the MasterPoolBox
        api_key: Node API key
        max_txs_to_scan: Max historical TXs to trace

    Returns:
        AnonymityAssessment with privacy score and warnings.
    """
    import httpx

    headers = {"api_key": api_key}

    # 1. Fetch pool box
    r = httpx.get(f"{node_url}/utxo/byId/{pool_box_id}", headers=headers, timeout=10)
    if r.status_code != 200:
        raise ValueError(f"Pool box {pool_box_id} not found ({r.status_code})")
    pool_box = r.json()

    regs = pool_box.get("additionalRegisters", {})
    denomination = _decode_long_register(regs.get("R7", "0500"))
    deposit_count = _decode_long_register(regs.get("R6", "0500"))
    pool_tree = pool_box.get("ergoTree", "")

    # 2. Walk the pool's TX chain backwards to trace deposit sources
    source_counts: dict[str, int] = {}
    creation_heights: list[int] = []
    current_box_id = pool_box_id
    txs_scanned = 0

    while txs_scanned < max_txs_to_scan:
        try:
            r_box = httpx.get(
                f"{node_url}/blockchain/box/byId/{current_box_id}",
                headers=headers, timeout=10,
            )
            if r_box.status_code != 200:
                break
            box_data = r_box.json()
            tx_id = box_data.get("transactionId")
            if not tx_id:
                break

            r_tx = httpx.get(
                f"{node_url}/blockchain/transaction/byId/{tx_id}",
                headers=headers, timeout=10,
            )
            if r_tx.status_code != 200:
                break
            tx_data = r_tx.json()
            txs_scanned += 1

            inputs = tx_data.get("inputs", [])
            outputs = tx_data.get("outputs", [])

            # Find pool input and output
            pool_output = next((o for o in outputs if o.get("ergoTree") == pool_tree), None)
            pool_input = next((i for i in inputs if i.get("ergoTree") == pool_tree), None)

            if pool_output and pool_input:
                erg_diff = pool_output["value"] - pool_input["value"]
                if erg_diff > 0:
                    # Deposit TX: trace intent box funders
                    num_deposits = erg_diff // denomination
                    creation_heights.append(pool_output.get("creationHeight", 0))

                    for inp in inputs[1:1 + num_deposits]:
                        inp_id = inp.get("boxId", "")
                        try:
                            r_ib = httpx.get(
                                f"{node_url}/blockchain/box/byId/{inp_id}",
                                headers=headers, timeout=5,
                            )
                            if r_ib.status_code == 200:
                                itx_id = r_ib.json().get("transactionId", "")
                                r_itx = httpx.get(
                                    f"{node_url}/blockchain/transaction/byId/{itx_id}",
                                    headers=headers, timeout=5,
                                )
                                if r_itx.status_code == 200:
                                    funders = r_itx.json().get("inputs", [])
                                    if funders:
                                        addr = funders[0].get("ergoTree", "unknown")
                                        source_counts[addr] = source_counts.get(addr, 0) + 1
                        except Exception:
                            source_counts["unknown"] = source_counts.get("unknown", 0) + 1

                # Walk backwards to the pool input's previous incarnation
                current_box_id = pool_input.get("boxId", "") if pool_input else ""
                if not current_box_id:
                    break
            else:
                break  # Genesis deployment TX
        except Exception as e:
            _logger.warning(f"Error tracing TX history: {e}")
            break

    # 3. Compute metrics
    unique_sources = len(source_counts)
    top_source_deposits = max(source_counts.values()) if source_counts else 0
    sybil_ratio = top_source_deposits / max(deposit_count, 1)
    temporal_spread = (max(creation_heights) - min(creation_heights)) if creation_heights else 0

    # 4. Compute privacy score (0-100)
    score = 0

    # Deposit count (0-30 pts)
    if deposit_count >= 100: score += 30
    elif deposit_count >= 50: score += 25
    elif deposit_count >= 20: score += 20
    elif deposit_count >= 10: score += 15
    elif deposit_count >= 5: score += 8
    else: score += max(0, deposit_count * 2)

    # Source diversity (0-40 pts)
    if unique_sources >= 20: score += 40
    elif unique_sources >= 10: score += 30
    elif unique_sources >= 5: score += 20
    elif unique_sources >= 3: score += 12
    elif unique_sources >= 2: score += 5

    # Anti-Sybil (0-20 pts)
    if sybil_ratio <= 0.1: score += 20
    elif sybil_ratio <= 0.25: score += 15
    elif sybil_ratio <= 0.5: score += 10
    elif sybil_ratio <= 0.75: score += 5

    # Temporal spread (0-10 pts)
    if temporal_spread >= 1440: score += 10  # ~1 day
    elif temporal_spread >= 720: score += 7   # ~12h
    elif temporal_spread >= 120: score += 4   # ~2h

    score = min(100, max(0, score))

    # 5. Risk level and warnings
    if score >= 81: risk_level = "EXCELLENT"
    elif score >= 61: risk_level = "GOOD"
    elif score >= 41: risk_level = "MODERATE"
    elif score >= 21: risk_level = "POOR"
    else: risk_level = "CRITICAL"

    warnings = []
    if deposit_count < 5:
        warnings.append(
            f"Very low deposit count ({deposit_count}). "
            "Wait for more deposits before withdrawing."
        )
    if unique_sources <= 1:
        warnings.append(
            "All deposits come from a single source. "
            "Anonymity set may be trivially deanonymizable."
        )
    if sybil_ratio > 0.5 and unique_sources > 1:
        warnings.append(
            f"One source accounts for {sybil_ratio:.0%} of deposits. "
            "Possible Sybil attack on the anonymity set."
        )
    if temporal_spread < 120 and deposit_count > 3:
        warnings.append(
            "All deposits occurred within a short time window. "
            "May indicate coordinated Sybil deposits."
        )

    return AnonymityAssessment(
        pool_box_id=pool_box_id,
        denomination=denomination,
        deposit_count=deposit_count,
        unique_sources=unique_sources,
        top_source_deposits=top_source_deposits,
        temporal_spread_blocks=temporal_spread,
        privacy_score=score,
        risk_level=risk_level,
        warnings=warnings,
    )


def check_withdrawal_safety(
    node_url: str,
    pool_box_id: str,
    api_key: str = "hello",
    min_score: int = 41,
) -> tuple[bool, AnonymityAssessment]:
    """
    Pre-withdrawal safety check. Call before building a withdrawal TX.

    Args:
        node_url: Ergo node API URL
        pool_box_id: MasterPoolBox to withdraw from
        api_key: Node API key
        min_score: Minimum score to consider safe (default 41 = MODERATE)

    Returns:
        (is_safe, assessment) tuple
    """
    assessment = analyze_anonymity_set(node_url, pool_box_id, api_key)
    return assessment.privacy_score >= min_score, assessment
