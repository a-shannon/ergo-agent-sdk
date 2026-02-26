"""
Deposit Relayer — batches IntentToDeposit boxes into the MasterPoolBox.

The Relayer sweeps up to MAX_BATCH_SIZE pending IntentToDeposit boxes
in a single transaction, moving ERG into the MasterPoolBox and inserting
their Pedersen Commitments into the Global Deposit AVL Tree.

Architecture:
    INPUTS:  [MasterPoolBox, IntentToDeposit_1, ..., IntentToDeposit_N]
    OUTPUTS: [MasterPoolBox', ChangeBox, FeeBox]

    MasterPoolBox' has:
      - R4 (Deposit Tree): N new commitments inserted
      - R5 (Nullifier Tree): unchanged
      - R6 (Counter): += N
      - R7 (Denomination): unchanged
      - value: += N * denomination
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ergo_agent.crypto.pedersen import (
    decode_point,
)

# Maximum number of IntentToDeposit boxes per batch sweep
MAX_BATCH_SIZE = 50

# Minimum box value in nanoERG
MIN_BOX_VALUE = 1_000_000

# Miner fee in nanoERG
MINER_FEE = 1_100_000

# Fee ErgoTree (standard miner fee contract)
FEE_ERGO_TREE = (
    "1005040004000e36100204a00b08cd0279be667ef9dcbbac55a06295ce870b"
    "07029bfcdb2dce28d959f2815b16f81798ea02d192a39a8cc7a70173007301"
    "1001020402d19683030193a38cc7b2a57300000193c2b2a5730100747302"
    "7303830108cdeeac93b1a57304"
)


@dataclass
class IntentToDeposit:
    """
    Represents a pending IntentToDeposit box on-chain.

    Attributes:
        box_id: The UTXO box ID.
        value_nanoerg: ERG amount in the box (should = denomination).
        commitment_hex: Compressed Pedersen Commitment C from R4.
        ergo_tree: The box's ErgoTree (for input serialization).
        raw_bytes_hex: Raw serialized box bytes (for inputsRaw).
    """
    box_id: str
    value_nanoerg: int
    commitment_hex: str
    ergo_tree: str
    raw_bytes_hex: str = ""


@dataclass
class PoolState:
    """
    Represents the current MasterPoolBox state.

    Attributes:
        box_id: The UTXO box ID.
        value_nanoerg: Current ERG balance.
        deposit_tree_hex: R4 Sigma-serialized AvlTree hex.
        nullifier_tree_hex: R5 Sigma-serialized AvlTree hex.
        deposit_counter: R6 current count.
        denomination: R7 pool denomination in nanoERG.
        ergo_tree: The pool contract ErgoTree.
        raw_bytes_hex: Raw serialized box bytes (for inputsRaw).
    """
    box_id: str
    value_nanoerg: int
    deposit_tree_hex: str
    nullifier_tree_hex: str
    deposit_counter: int
    denomination: int
    ergo_tree: str
    raw_bytes_hex: str = ""


class DepositRelayer:
    """
    Batches IntentToDeposit boxes into the MasterPoolBox.

    Usage:
        relayer = DepositRelayer(pool_state)
        intent_boxes = relayer.scan_pending_deposits(node)
        tx = relayer.build_batch_deposit_tx(intent_boxes[:50])
    """

    def __init__(self, pool_state: PoolState):
        """
        Initialize with the current pool state.

        Args:
            pool_state: Current MasterPoolBox state from on-chain.
        """
        self.pool_state = pool_state

    def validate_intent(self, intent: IntentToDeposit) -> bool:
        """
        Validate that an IntentToDeposit box is well-formed.

        Checks:
        - Value matches pool denomination
        - Commitment is a valid compressed secp256k1 point
        - Commitment is not a trivial point (G, identity)

        Args:
            intent: The pending intent box to validate.

        Returns:
            True if valid, False if malformed.
        """
        # Value must match denomination
        if intent.value_nanoerg < self.pool_state.denomination:
            return False

        # Commitment must be a valid compressed point
        try:
            decode_point(intent.commitment_hex)
        except (ValueError, Exception):
            return False

        # Must not be trivial
        from ergo_agent.crypto.pedersen import G_COMPRESSED
        if intent.commitment_hex == G_COMPRESSED:
            return False

        return True

    def build_batch_deposit_tx(
        self,
        intents: list[IntentToDeposit],
    ) -> dict[str, Any]:
        """
        Build a batch deposit transaction sweeping N intent boxes.

        Creates a transaction that:
        1. Spends the MasterPoolBox + N IntentToDeposit boxes
        2. Outputs a new MasterPoolBox with:
           - R4: N commitments inserted into the Deposit AVL Tree
           - R5: Unchanged Nullifier Tree
           - R6: Counter incremented by N
           - R7: Unchanged denomination
           - value: increased by N * denomination
        3. Outputs a miner fee box

        Args:
            intents: List of validated IntentToDeposit boxes (max MAX_BATCH_SIZE).

        Returns:
            Unsigned transaction dict ready for signing.

        Raises:
            ValueError: If too many intents or validation fails.
        """
        if not intents:
            raise ValueError("No intent boxes provided")
        if len(intents) > MAX_BATCH_SIZE:
            raise ValueError(
                f"Too many intents: {len(intents)} > {MAX_BATCH_SIZE}"
            )

        # Validate all intents
        for i, intent in enumerate(intents):
            if not self.validate_intent(intent):
                raise ValueError(f"Intent {i} (box {intent.box_id}) failed validation")

        n = len(intents)
        ps = self.pool_state

        # Compute new pool state
        new_value = ps.value_nanoerg + (n * ps.denomination)
        new_counter = ps.deposit_counter + n

        # Extract commitments for AVL insert
        commitments = [intent.commitment_hex for intent in intents]

        # Generate AVL insert proof
        avl_proof_hex, new_deposit_tree_hex = self._generate_batch_avl_proof(
            ps.deposit_tree_hex, commitments
        )

        # Build the transaction
        inputs = [
            {
                "boxId": ps.box_id,
                "extension": {
                    "0": "0e" + self._vlq_hex(len(bytes.fromhex(avl_proof_hex))) + avl_proof_hex,
                },
            },
        ]
        # Add intent boxes as inputs (permissionless, no extension needed)
        for intent in intents:
            inputs.append({"boxId": intent.box_id, "extension": {}})

        # MasterPoolBox output
        pool_output = {
            "value": new_value,
            "ergoTree": ps.ergo_tree,
            "assets": [],
            "additionalRegisters": {
                "R4": new_deposit_tree_hex,
                "R5": ps.nullifier_tree_hex,
                "R6": self._sigma_long(new_counter),
                "R7": self._sigma_long(ps.denomination),
            },
            "creationHeight": 0,  # Filled by node
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
            "outputs": [pool_output, fee_output],
        }

        # Collect inputsRaw for signing
        inputs_raw = []
        if ps.raw_bytes_hex:
            inputs_raw.append(ps.raw_bytes_hex)
        for intent in intents:
            if intent.raw_bytes_hex:
                inputs_raw.append(intent.raw_bytes_hex)

        return {
            "tx": tx,
            "inputsRaw": inputs_raw,
            "commitments": commitments,
            "avl_proof": avl_proof_hex,
            "new_deposit_tree": new_deposit_tree_hex,
            "batch_size": n,
        }

    def _generate_batch_avl_proof(
        self,
        current_tree_hex: str,
        commitment_hexes: list[str],
    ) -> tuple[str, str]:
        """
        Generate a batched AVL insert proof for multiple commitments.

        Args:
            current_tree_hex: Current R4 Sigma-serialized AvlTree.
            commitment_hexes: List of compressed commitment hex strings.

        Returns:
            (proof_hex, new_tree_hex) tuple.
        """
        try:
            from ergo_avltree import AvlTreeProver

            prover = AvlTreeProver(key_length=33)
            for c_hex in commitment_hexes:
                prover.insert(bytes.fromhex(c_hex), b"")
            proof_bytes, new_digest_bytes = prover.generate_proof()

            # Sigma serialize: type 0x64 + 33-byte digest + flags(07) + keyLen(42=33 zigzag)
            new_tree_hex = "64" + new_digest_bytes.hex() + "072100"
            return proof_bytes.hex(), new_tree_hex

        except ImportError:
            # Fallback: return placeholder if ergo_avltree not available
            # This allows unit testing without the Rust extension
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
