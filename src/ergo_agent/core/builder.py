"""
TransactionBuilder: high-level transaction construction for Ergo.

This builder constructs the unsigned transaction dict in the format
expected by the Ergo node API. The resulting dict can be signed
by the Wallet class and submitted via ErgoNode.submit_transaction().
"""

from __future__ import annotations

from typing import Any

from ergo_agent.core.address import address_to_ergo_tree, validate_address
from ergo_agent.core.models import NANOERG_PER_ERG, Box

# Ergo minimum fee — 0.0011 ERG in nanoERG
MIN_FEE_NANOERG = 1_100_000
# Ergo minimum box value — to avoid "dust" rejection
MIN_BOX_VALUE_NANOERG = 1_000_000

# Ergo fee ErgoTree (constant — pays miners)
FEE_ERGO_TREE = (
    "1005040004000e36100204a00b08cd0279be667ef9dcbbac55a06295ce870b"
    "07029bfcdb2dce28d959f2815b16f81798ea02d192a39a8cc7a70173007301"
    "1001020402d19683030193a38cc7b2a57300000193c2b2a5730100747302"
    "7303830108cdeeac93b1a57304"
)


class TransactionBuilderError(Exception):
    pass


class TransactionBuilder:
    """
    Fluent builder for Ergo unsigned transactions.

    Usage (simple transfer):
        tx = (
            TransactionBuilder(node, wallet)
            .send(to="9f...", amount_erg=1.5)
            .with_fee(0.001)
            .build()
        )

    Usage (contract interaction with context extensions):
        tx = (
            TransactionBuilder(node, wallet)
            .with_input(pool_box, extension={"0": key_image_hex, "1": proof_hex})
            .add_output_raw(ergo_tree=..., value_nanoerg=..., tokens=[...], registers={...})
            .build()
        )

    The builder:
    - Validates all destination addresses (checksum + network byte)
    - Supports explicit input boxes (for spending contract UTXOs)
    - Supports context extensions on inputs (for getVar() in ErgoScript)
    - Automatically selects additional wallet UTXOs if explicit inputs aren't enough
    - Converts addresses to ErgoTree hex (P2PK direct, P2S/P2SH via API)
    - Calculates change output
    - Returns an unsigned tx dict ready for signing
    """

    def __init__(self, node: Any, wallet: Any) -> None:
        self._node = node
        self._wallet = wallet
        self._outputs: list[dict[str, Any]] = []
        self._explicit_inputs: list[dict[str, Any]] = []  # Explicitly specified inputs
        self._data_inputs: list[dict[str, Any]] = []
        self._fee_nanoerg: int = MIN_FEE_NANOERG
        # Cache ErgoTree lookups to avoid repeated API calls
        self._ergo_tree_cache: dict[str, str] = {}

    def send(self, to: str, amount_erg: float) -> TransactionBuilder:
        """Add a simple ERG transfer output."""
        if amount_erg <= 0:
            raise TransactionBuilderError("Amount must be positive.")
        validate_address(to)
        self._outputs.append({
            "type": "send_erg",
            "address": to,
            "amount_nanoerg": int(amount_erg * NANOERG_PER_ERG),
        })
        return self

    def send_token(self, to: str, token_id: str, amount: int) -> TransactionBuilder:
        """Add a token transfer output (also sends minimum ERG dust to the box)."""
        validate_address(to)
        self._outputs.append({
            "type": "send_token",
            "address": to,
            "token_id": token_id,
            "token_amount": amount,
            "amount_nanoerg": MIN_BOX_VALUE_NANOERG,
        })
        return self

    def add_output_raw(
        self,
        ergo_tree: str,
        value_nanoerg: int,
        tokens: list[dict[str, Any]] | None = None,
        registers: dict[str, str] | None = None,
    ) -> TransactionBuilder:
        """Add a raw output box (for custom contract interactions like DEX swaps)."""
        self._outputs.append({
            "type": "raw",
            "ergo_tree": ergo_tree,
            "amount_nanoerg": value_nanoerg,
            "tokens": tokens or [],
            "registers": registers or {},
        })
        return self

    def with_input(
        self,
        box: Box | str,
        extension: dict[str, str] | None = None,
    ) -> TransactionBuilder:
        """
        Add an explicit input box (for spending contract boxes like PoolBoxes).

        Args:
            box: a Box object or a box ID string. If a string, the box will
                 be fetched from the node when build() is called.
            extension: context extension variables for this input.
                       Keys are variable IDs (as strings, e.g. "0", "1"),
                       values are serialized hex strings.
                       These correspond to getVar[T](id) calls in ErgoScript.

        Example:
            builder.with_input(pool_box, extension={
                "0": key_image_group_element_hex,
                "1": avl_tree_insert_proof_hex,
            })
        """
        if isinstance(box, str):
            # Will be resolved at build() time
            self._explicit_inputs.append({
                "box_id": box,
                "box": None,
                "extension": extension or {},
            })
        else:
            self._explicit_inputs.append({
                "box_id": box.box_id,
                "box": box,
                "extension": extension or {},
            })
        return self

    def with_data_input(self, box_id: str) -> TransactionBuilder:
        """Add a read-only data input (for oracle price reads, etc.)."""
        self._data_inputs.append({"boxId": box_id})
        return self

    def with_fee(self, fee_erg: float) -> TransactionBuilder:
        """Set a custom fee. Default is MIN_FEE (0.0011 ERG)."""
        self._fee_nanoerg = int(fee_erg * NANOERG_PER_ERG)
        return self

    def build(self) -> dict[str, Any]:
        """
        Build the unsigned transaction dict.

        Supports three input modes:
        1. Auto-selection only (default): selects wallet UTXOs to cover outputs + fee
        2. Explicit only: uses only with_input() boxes
        3. Mixed: explicit inputs first, then auto-selects wallet UTXOs for the remainder

        Returns:
            dict: unsigned transaction in Ergo API format
        """
        # Total nanoERG needed (outputs + fee)
        total_needed = sum(o["amount_nanoerg"] for o in self._outputs) + self._fee_nanoerg

        # --- Resolve explicit inputs ---
        input_entries: list[dict[str, Any]] = []
        total_input = 0
        explicit_box_ids: set[str] = set()

        for ei in self._explicit_inputs:
            box = ei["box"]
            if box is None:
                # Fetch box by ID from the node
                box = self._node.get_box_by_id(ei["box_id"])
                if box is None:
                    raise TransactionBuilderError(
                        f"Box not found: {ei['box_id']}"
                    )
            input_entries.append({
                "boxId": box.box_id,
                "spendingProof": {
                    "proofBytes": "",
                    "extension": ei["extension"],
                },
            })
            total_input += box.value
            explicit_box_ids.add(box.box_id)

        # --- Auto-select wallet UTXOs for the remainder (if needed) ---
        remaining = total_needed - total_input
        if remaining > 0:
            available_boxes = self._node.get_unspent_boxes(self._wallet.address)
            if not available_boxes:
                raise TransactionBuilderError(
                    f"No unspent boxes found for address {self._wallet.address}."
                )
            # Exclude any boxes already explicitly included
            available_boxes = [
                b for b in available_boxes if b.box_id not in explicit_box_ids
            ]
            selected, selected_total = self._select_boxes(available_boxes, remaining)
            for b in selected:
                input_entries.append({
                    "boxId": b.box_id,
                    "spendingProof": {"proofBytes": "", "extension": {}},
                })
            total_input += selected_total

        # Compute change
        change_nanoerg = total_input - total_needed
        if change_nanoerg < 0:
            balance_erg = total_input / NANOERG_PER_ERG
            needed_erg = total_needed / NANOERG_PER_ERG
            raise TransactionBuilderError(
                f"Insufficient funds: have {balance_erg:.4f} ERG, need {needed_erg:.4f} ERG."
            )

        # Build outputs
        current_height = self._node.get_height()
        outputs = []
        for out in self._outputs:
            if out["type"] == "raw":
                # Raw output -- ErgoTree already provided
                box: dict[str, Any] = {
                    "value": out["amount_nanoerg"],
                    "ergoTree": out["ergo_tree"],
                    "creationHeight": current_height,
                    "assets": out.get("tokens", []),
                    "additionalRegisters": out.get("registers", {}),
                }
            else:
                # Address-based output -- convert to ErgoTree
                box = {
                    "value": out["amount_nanoerg"],
                    "ergoTree": self._resolve_ergo_tree(out["address"]),
                    "creationHeight": current_height,
                    "assets": [],
                    "additionalRegisters": {},
                }
                if out["type"] == "send_token":
                    box["assets"] = [
                        {"tokenId": out["token_id"], "amount": out["token_amount"]}
                    ]
            outputs.append(box)

        # Fee output (pays to miners)
        outputs.append({
            "value": self._fee_nanoerg,
            "ergoTree": FEE_ERGO_TREE,
            "creationHeight": current_height,
            "assets": [],
            "additionalRegisters": {},
        })

        # Change output (back to sender)
        if change_nanoerg >= MIN_BOX_VALUE_NANOERG:
            outputs.append({
                "value": change_nanoerg,
                "ergoTree": self._resolve_ergo_tree(self._wallet.address),
                "creationHeight": current_height,
                "assets": [],
                "additionalRegisters": {},
            })

        return {
            "inputs": input_entries,
            "dataInputs": self._data_inputs,
            "outputs": outputs,
        }

    def _resolve_ergo_tree(self, address: str) -> str:
        """Convert address to ErgoTree, with caching."""
        if address not in self._ergo_tree_cache:
            self._ergo_tree_cache[address] = address_to_ergo_tree(
                address, self._node.node_url
            )
        return self._ergo_tree_cache[address]

    def _select_boxes(
        self, boxes: list[Box], amount_needed: int
    ) -> tuple[list[Box], int]:
        """Greedy UTXO selection: pick boxes until we have enough."""
        selected = []
        total = 0
        for box in sorted(boxes, key=lambda b: b.value, reverse=True):
            selected.append(box)
            total += box.value
            if total >= amount_needed:
                return selected, total
        raise TransactionBuilderError(
            f"Insufficient funds: only {total / NANOERG_PER_ERG:.4f} ERG available."
        )
