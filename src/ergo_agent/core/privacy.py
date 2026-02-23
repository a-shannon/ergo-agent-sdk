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
# Derived deterministically: SHA256("CASH.v3.second.generator.H.0")
# → x-coordinate on secp256k1, verified on-curve, compressed encoding.
# Nobody knows the discrete log of H w.r.t. G because x is a hash output.
#
# Verification:
#   import hashlib
#   h = hashlib.sha256(b"CASH.v3.second.generator.H.0").digest()
#   x = int.from_bytes(h, 'big')
#   # x^3 + 7 mod p is a quadratic residue → valid curve point
#
NUMS_H_HEX = "02eab569326ae73e525b96643b2c31300e822007c91faf0c356226c4942ebe9eb2"

# ==============================================================================
# Pool Contract ErgoScript Source
# ==============================================================================

# Withdrawal path — the main privacy contract
POOL_WITHDRAW_SCRIPT = '''
{
  val keys     = SELF.R4[Coll[GroupElement]].get
  val denom    = SELF.R6[Long].get
  val poolOut  = OUTPUTS(0)
  val ringOk   = keys.size >= 2
  val keyImage     = getVar[GroupElement](0).get
  val insertProof  = getVar[Coll[Byte]](1).get
  val H = decodePoint(fromBase16("''' + NUMS_H_HEX + '''"))
  val keyImageSafe = keyImage != groupGenerator
  val keyImageNotH = keyImage != H
  val curTree  = SELF.R5[AvlTree].get
  val newTree  = curTree.insert(
    Coll((keyImage.getEncoded, Coll[Byte]())),
    insertProof
  ).get
  val treeOk   = poolOut.R5[AvlTree].get.digest == newTree.digest
  val tokenIdOk = poolOut.tokens(0)._1 == SELF.tokens(0)._1
  val tokenOk  = poolOut.tokens(0)._2 == SELF.tokens(0)._2 - denom
  val keysOk   = poolOut.R4[Coll[GroupElement]].get == keys
  val scriptOk = poolOut.propositionBytes == SELF.propositionBytes
  val denomOk  = poolOut.R6[Long].get == denom
  val withdrawOut = OUTPUTS(1)
  val withdrawOk  = withdrawOut.tokens(0)._1 == SELF.tokens(0)._1 &&
                    withdrawOut.tokens(0)._2 == denom
  val ringProof = atLeast(1, keys.map { (pk: GroupElement) =>
    proveDlog(pk) && proveDHTuple(groupGenerator, H, pk, keyImage)
  })
  sigmaProp(ringOk && treeOk && tokenIdOk && tokenOk && keysOk &&
            scriptOk && denomOk && withdrawOk &&
            keyImageSafe && keyImageNotH) && ringProof
}
'''

# Deposit path
POOL_DEPOSIT_SCRIPT = '''
{
  val keys     = SELF.R4[Coll[GroupElement]].get
  val denom    = SELF.R6[Long].get
  val maxN     = SELF.R7[Int].get
  val poolOut  = OUTPUTS(0)
  val tokenIdOk     = poolOut.tokens(0)._1 == SELF.tokens(0)._1
  val depositAmount = poolOut.tokens(0)._2 - SELF.tokens(0)._2
  val tokenOk       = depositAmount > 0L && (depositAmount % denom) == 0L
  val tickets       = depositAmount / denom
  val newKeys  = poolOut.R4[Coll[GroupElement]].get
  val spaceOk  = newKeys.size <= maxN
  val sizeOk   = newKeys.size == keys.size + tickets
  val oldKeysOk = keys.indices.forall { (i: Int) =>
    newKeys(i) == keys(i)
  }
  val newKey       = newKeys(keys.size)
  val newKeyValid  = newKey != groupGenerator
  val uniqueKeyOk  = keys.forall { (pk: GroupElement) => pk != newKey }
  val scriptOk = poolOut.propositionBytes == SELF.propositionBytes
  val denomOk  = poolOut.R6[Long].get == denom
  val maxOk    = poolOut.R7[Int].get == maxN
  val treeOk   = poolOut.R5[AvlTree].get.digest == SELF.R5[AvlTree].get.digest
  sigmaProp(tokenIdOk && tokenOk && spaceOk && sizeOk && oldKeysOk &&
            newKeyValid && uniqueKeyOk &&
            scriptOk && denomOk && maxOk && treeOk)
}
'''

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

def generate_fresh_secret() -> tuple[str, str]:
    """
    Securely generates a fresh mathematical secret (private key) and its 
    corresponding public key (compressed secp256k1 point) for a pool deposit.
    
    Returns:
        tuple: (private_key_hex, public_key_compressed_hex)
    """
    # 1. Generate 32-byte secure random secret
    priv_key_bytes = secrets.token_bytes(32)
    
    # 2. Derive public key using secp256k1
    signing_key = ecdsa.SigningKey.from_string(priv_key_bytes, curve=ecdsa.SECP256k1)
    verifying_key = signing_key.get_verifying_key()
    
    # 3. Compress the public key (Ergo GroupElement format)
    x = verifying_key.pubkey.point.x()
    y = verifying_key.pubkey.point.y()
    prefix = b"\\x02" if y % 2 == 0 else b"\\x03"
    
    pub_key_compressed = prefix + x.to_bytes(32, byteorder="big")
    
    return priv_key_bytes.hex(), pub_key_compressed.hex()



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
    key_image_hex: str,
    avl_insert_proof_hex: str,
    recipient_ergo_tree: str,
    pool_ergo_tree: str,
    pool_token_id: str,
    denomination: int,
) -> dict[str, Any]:
    """
    Build a withdrawal transaction: ring-signature proof to withdraw from a PoolBox.

    The key image (nullifier) is passed as context extension var 0.
    The AvlTree insert proof is passed as context extension var 1.
    The ring proof is generated by the node's prover at signing time.

    Args:
        builder: a TransactionBuilder instance
        pool_box: the PoolBox to withdraw from
        key_image_hex: serialized key image GroupElement (nullifier)
        avl_insert_proof_hex: serialized AvlTree insert proof bytes
        recipient_ergo_tree: ErgoTree of the withdrawal recipient
        pool_ergo_tree: ErgoTree hex of the pool contract
        pool_token_id: the privacy pool token ID
        denomination: amount to withdraw (must match pool's R6)

    Returns:
        unsigned transaction dict
    """
    current_reserve = 0
    for t in pool_box.tokens:
        if t.token_id == pool_token_id:
            current_reserve = t.amount
            break

    new_reserve = current_reserve - denomination

    # Context extension: pass key image and insert proof to the script
    extension = {
        "0": key_image_hex,       # getVar[GroupElement](0) in ErgoScript
        "1": avl_insert_proof_hex,  # getVar[Coll[Byte]](1) in ErgoScript
    }

    tx = (
        builder
        .with_input(pool_box, extension=extension)  # Pool with ring proof context
        .add_output_raw(
            ergo_tree=pool_ergo_tree,
            value_nanoerg=pool_box.value,
            tokens=[{"tokenId": pool_token_id, "amount": new_reserve}],
            registers={
                "R4": pool_box.additional_registers.get("R4", ""),  # Keys unchanged
                "R5": "",  # Updated nullifier tree (new digest) — TODO: serialize
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

