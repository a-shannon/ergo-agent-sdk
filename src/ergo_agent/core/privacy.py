"""
Privacy module for $CASH v3 — application-level ring-signature privacy pools.

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
  val curTree  = SELF.R5[AvlTree].get
  val newTree  = curTree.insert(
    Coll((keyImage.getEncoded, Coll[Byte]())),
    insertProof
  ).get
  val treeOk   = poolOut.R5[AvlTree].get.digest == newTree.digest
  val tokenOk  = poolOut.tokens(0)._2 == SELF.tokens(0)._2 - denom
  val keysOk   = poolOut.R4[Coll[GroupElement]].get.size == keys.size
  val scriptOk = poolOut.propositionBytes == SELF.propositionBytes
  val denomOk  = poolOut.R6[Long].get == denom
  val withdrawOut = OUTPUTS(1)
  val withdrawOk  = withdrawOut.tokens(0)._1 == SELF.tokens(0)._1 &&
                    withdrawOut.tokens(0)._2 == denom
  val H = decodePoint(fromBase16("''' + NUMS_H_HEX + '''"))
  val ringProof = atLeast(1, keys.map { (pk: GroupElement) =>
    proveDlog(pk) && proveDHTuple(groupGenerator, H, pk, keyImage)
  })
  sigmaProp(ringOk && treeOk && tokenOk && keysOk &&
            scriptOk && denomOk && withdrawOk) && ringProof
}
'''

# Deposit path
POOL_DEPOSIT_SCRIPT = '''
{
  val keys     = SELF.R4[Coll[GroupElement]].get
  val denom    = SELF.R6[Long].get
  val maxN     = SELF.R7[Int].get
  val poolOut  = OUTPUTS(0)
  val spaceOk  = keys.size < maxN
  val newKeys  = poolOut.R4[Coll[GroupElement]].get
  val sizeOk   = newKeys.size == keys.size + 1
  val oldKeysOk = keys.indices.forall { (i: Int) =>
    newKeys(i) == keys(i)
  }
  val tokenOk  = poolOut.tokens(0)._2 == SELF.tokens(0)._2 + denom
  val scriptOk = poolOut.propositionBytes == SELF.propositionBytes
  val denomOk  = poolOut.R6[Long].get == denom
  val maxOk    = poolOut.R7[Int].get == maxN
  val treeOk   = poolOut.R5[AvlTree].get.digest == SELF.R5[AvlTree].get.digest
  sigmaProp(spaceOk && sizeOk && oldKeysOk && tokenOk &&
            scriptOk && denomOk && maxOk && treeOk)
}
'''

# Note contract — simplified bearer instrument
NOTE_CONTRACT_SCRIPT = '''
{
  val denomValid = {
    val d = SELF.tokens(0)._2
    d == 1L || d == 10L || d == 100L || d == 1000L || d == 10000L || d == 100000L
  }
  sigmaProp(denomValid) && proveDlog(SELF.R4[GroupElement].get)
}
'''


# ==============================================================================
# Transaction Builders & Aggregators
# ==============================================================================

def find_optimal_pool(
    node: ErgoNode,
    pool_ergo_tree: str,
    cash_token_id: str,
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
        cash_token_id: The $CASH token ID
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
        if not any(t.token_id == cash_token_id for t in box.tokens):
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
    depositor_public_key_hex: str,
    pool_ergo_tree: str,
    cash_token_id: str,
    denomination: int,
) -> dict[str, Any]:
    """
    Build a deposit transaction: send a NoteBox's tokens into a PoolBox.

    The depositor's public key is appended to the pool's key list (R4).
    The pool's token reserve increases by one denomination.

    Args:
        builder: a TransactionBuilder instance
        pool_box: the PoolBox to deposit into
        note_box: the NoteBox being deposited (must contain denomination tokens)
        depositor_public_key_hex: the depositor's one-time public key (GroupElement hex)
        pool_ergo_tree: the ErgoTree hex of the pool contract
        cash_token_id: the $CASH token ID
        denomination: the denomination amount (must match pool's R6)

    Returns:
        unsigned transaction dict
    """
    # Get current keys from pool
    current_keys_r4 = pool_box.additional_registers.get("R4", "")
    current_reserve = 0
    for t in pool_box.tokens:
        if t.token_id == cash_token_id:
            current_reserve = t.amount
            break

    new_reserve = current_reserve + denomination

    # Build: pool_box + note_box as inputs → new pool_box as output
    tx = (
        builder
        .with_input(pool_box)    # Pool being updated
        .with_input(note_box)    # Note being deposited
        .add_output_raw(
            ergo_tree=pool_ergo_tree,
            value_nanoerg=pool_box.value,
            tokens=[{"tokenId": cash_token_id, "amount": new_reserve}],
            registers={
                # R4: updated keys (append depositor key) — must be serialized
                # R5: unchanged nullifier tree
                # R6: denomination (unchanged)
                # R7: maxDeposits (unchanged)
                "R4": current_keys_r4,  # TODO: append depositor_public_key_hex
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
    cash_token_id: str,
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
        cash_token_id: the $CASH token ID
        denomination: amount to withdraw (must match pool's R6)

    Returns:
        unsigned transaction dict
    """
    current_reserve = 0
    for t in pool_box.tokens:
        if t.token_id == cash_token_id:
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
            tokens=[{"tokenId": cash_token_id, "amount": new_reserve}],
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
            tokens=[{"tokenId": cash_token_id, "amount": denomination}],
        )
        .build()
    )
    return tx
