"""
Withdrawal Relayer — processes IntentToWithdraw boxes 1-by-1 sequentially.

The Relayer takes exactly one IntentToWithdraw box per transaction,
verifying the DHTuple ring proof and inserting the nullifier into
the MasterPoolBox's Nullifier AVL Tree.

Architecture:
    INPUTS:  [MasterPoolBox, IntentToWithdrawBox]
    OUTPUTS: [MasterPoolBox', PayoutBox, FeeBox]

    MasterPoolBox' has:
      - R4 (Deposit Tree): unchanged
      - R5 (Nullifier Tree): nullifier I inserted
      - R6 (Counter): unchanged
      - R7 (Denomination): unchanged
      - value: -= denomination

Sequential Constraint:
    Because Ergo's Sigma protocol hashes tx.messageToSign into the
    Fiat-Shamir challenge, the Relayer CANNOT batch multiple independent
    withdrawals. Each withdrawal must be its own transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ergo_agent.crypto.pedersen import G_COMPRESSED, NUMS_H, decode_point
from ergo_agent.relayer.deposit_relayer import (
    FEE_ERGO_TREE,
    MINER_FEE,
    PoolState,
)


@dataclass
class IntentToWithdraw:
    """
    Represents a pending IntentToWithdraw box on-chain.

    Attributes:
        box_id: The UTXO box ID.
        value_nanoerg: ERG amount in the box (minimum box value).
        nullifier_hex: Compressed nullifier I = r·H from R4.
        secondary_gen_hex: Deprecated (v9). U is no longer user-supplied;
            the contract uses U_global = H. Set to None.
        payout_ergo_tree: Target payout address ErgoTree bytes (from R6).
        ergo_tree: The box's ErgoTree.
        raw_bytes_hex: Raw serialized box bytes (for inputsRaw).
    """
    box_id: str
    value_nanoerg: int
    nullifier_hex: str
    secondary_gen_hex: str | None  # Deprecated v9 — U=H hardcoded in contract
    payout_ergo_tree: str
    ergo_tree: str
    raw_bytes_hex: str = ""


class WithdrawalRelayer:
    """
    Processes IntentToWithdraw boxes one at a time.

    Usage:
        relayer = WithdrawalRelayer(pool_state)
        intent = relayer.scan_pending_withdrawals(node)[0]
        tx = relayer.build_withdrawal_tx(intent)
    """

    def __init__(self, pool_state: PoolState):
        """
        Initialize with the current pool state.

        Args:
            pool_state: Current MasterPoolBox state from on-chain.
        """
        self.pool_state = pool_state

    def validate_intent(self, intent: IntentToWithdraw) -> bool:
        """
        Validate that an IntentToWithdraw box is well-formed.

        Checks:
        - Nullifier is a valid compressed secp256k1 point
        - Nullifier is not G or H (trivial points)
        - Payout address is non-empty
        - Pool has sufficient ERG for withdrawal

        Note: Secondary generator (U) is no longer validated here.
        In v9, U_global = H is hardcoded in the contract; the intent box
        does not carry a user-supplied U (CRIT-2 fix).

        Args:
            intent: The pending intent box to validate.

        Returns:
            True if valid, False if malformed.
        """
        # Nullifier must be a valid point
        try:
            decode_point(intent.nullifier_hex)
        except (ValueError, Exception):
            return False

        # Nullifier must not be trivial
        if intent.nullifier_hex == G_COMPRESSED:
            return False
        if intent.nullifier_hex == NUMS_H:
            return False

        # Payout address must be non-empty
        if not intent.payout_ergo_tree:
            return False

        # Pool must have enough ERG
        if self.pool_state.value_nanoerg < self.pool_state.denomination + MINER_FEE:
            return False

        return True

    def build_withdrawal_tx(
        self,
        intent: IntentToWithdraw,
    ) -> dict[str, Any]:
        """
        Build a sequential withdrawal transaction for exactly 1 intent.

        Creates a transaction that:
        1. Spends the MasterPoolBox + 1 IntentToWithdraw box
        2. Outputs a new MasterPoolBox with:
           - R4: Unchanged Deposit Tree
           - R5: Nullifier inserted into Nullifier Tree
           - R6: Unchanged counter
           - R7: Unchanged denomination
           - value: decreased by denomination
        3. Outputs a payout box to the recipient
        4. Outputs a miner fee box

        Args:
            intent: A validated IntentToWithdraw box.

        Returns:
            Unsigned transaction dict ready for signing.

        Raises:
            ValueError: If validation fails.
        """
        if not self.validate_intent(intent):
            raise ValueError(f"Intent {intent.box_id} failed validation")

        ps = self.pool_state

        # Generate nullifier AVL insert proof
        null_proof_hex, new_null_tree_hex = self._generate_nullifier_proof(
            ps.nullifier_tree_hex, intent.nullifier_hex
        )

        # New pool value
        new_value = ps.value_nanoerg - ps.denomination

        # Build inputs
        inputs = [
            {
                "boxId": ps.box_id,
                "extension": {
                    # Var 1: nullifier AVL insert proof
                    "1": "0e" + self._vlq_hex(len(bytes.fromhex(null_proof_hex))) + null_proof_hex,
                },
            },
            {
                "boxId": intent.box_id,
                "extension": {},
            },
        ]

        # MasterPoolBox output (R4 unchanged, R5 updated, R6/R7 unchanged)
        pool_output = {
            "value": new_value,
            "ergoTree": ps.ergo_tree,
            "assets": [],
            "additionalRegisters": {
                "R4": ps.deposit_tree_hex,
                "R5": new_null_tree_hex,
                "R6": self._sigma_long(ps.deposit_counter),
                "R7": self._sigma_long(ps.denomination),
            },
            "creationHeight": 0,
        }

        # Payout output — recipient gets denomination ERG
        payout_output = {
            "value": ps.denomination,
            "ergoTree": intent.payout_ergo_tree,
            "assets": [],
            "additionalRegisters": {},
            "creationHeight": 0,
        }

        # Fee output
        fee_output = {
            "value": MINER_FEE,
            "ergoTree": FEE_ERGO_TREE,
            "assets": [],
            "additionalRegisters": {},
            "creationHeight": 0,
        }

        tx = {
            "inputs": inputs,
            "dataInputs": [],
            "outputs": [pool_output, payout_output, fee_output],
        }

        # Collect inputsRaw
        inputs_raw = []
        if ps.raw_bytes_hex:
            inputs_raw.append(ps.raw_bytes_hex)
        if intent.raw_bytes_hex:
            inputs_raw.append(intent.raw_bytes_hex)

        return {
            "tx": tx,
            "inputsRaw": inputs_raw,
            "nullifier": intent.nullifier_hex,
            "null_proof": null_proof_hex,
            "new_null_tree": new_null_tree_hex,
            "payout_address": intent.payout_ergo_tree,
        }

    def _generate_nullifier_proof(
        self,
        current_null_tree_hex: str,
        nullifier_hex: str,
    ) -> tuple[str, str]:
        """
        Generate an AVL insert proof for the nullifier.

        Args:
            current_null_tree_hex: Current R5 Sigma-serialized AvlTree.
            nullifier_hex: Compressed nullifier point (66 hex chars).

        Returns:
            (proof_hex, new_tree_hex) tuple.
        """
        try:
            from ergo_avltree import AvlTreeProver

            prover = AvlTreeProver(key_length=33)
            prover.insert(bytes.fromhex(nullifier_hex), b"")
            proof_bytes, new_digest_bytes = prover.generate_proof()

            new_tree_hex = "64" + new_digest_bytes.hex() + "072100"
            return proof_bytes.hex(), new_tree_hex

        except ImportError:
            # Fallback for unit testing without Rust extension
            placeholder_digest = "00" * 33
            new_tree_hex = "64" + placeholder_digest + "072100"
            return "00", new_tree_hex

    @staticmethod
    def _vlq_hex(n: int) -> str:
        """Encode integer as VLQ hex."""
        result: list[int] = []
        while n >= 0x80:
            result.append((n & 0x7F) | 0x80)
            n >>= 7
        result.append(n)
        return bytes(result).hex()

    @staticmethod
    def _sigma_long(n: int) -> str:
        """Encode integer as Sigma-serialized Long (type 0x05 + zigzag VLQ)."""
        zigzag = (n << 1) ^ (n >> 63)
        result: list[int] = []
        while zigzag >= 0x80:
            result.append((zigzag & 0x7F) | 0x80)
            zigzag >>= 7
        result.append(zigzag)
        return "05" + bytes(result).hex()
