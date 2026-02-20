"""
TransactionBuilder: high-level transaction construction for Ergo.

This builder constructs the unsigned transaction dict in the format
expected by the Ergo node API. The resulting dict can be signed
by the Wallet class and submitted via ErgoNode.submit_transaction().
"""

from __future__ import annotations

from typing import Any

from ergo_lib_python.chain import Constant

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

    def send_funds(self, to: str, amount_erg: float, tokens: dict[str, int] | None = None) -> TransactionBuilder:
        """Add a transfer output sending ERG and optionally multiple tokens."""
        if amount_erg <= 0:
            raise TransactionBuilderError("Amount must be positive.")
        validate_address(to)
        self._outputs.append({
            "type": "send_funds",
            "address": to,
            "amount_nanoerg": int(amount_erg * NANOERG_PER_ERG),
            "tokens": tokens or {},
        })
        return self

    def send(self, to: str, amount_erg: float) -> TransactionBuilder:
        """Add a simple ERG transfer output. (Deprecated: use send_funds)"""
        return self.send_funds(to, amount_erg)

    def send_token(self, to: str, token_id: str, amount: int) -> TransactionBuilder:
        """Add a token transfer output (also sends minimum ERG dust to the box)."""
        return self.send_funds(to, MIN_BOX_VALUE_NANOERG / NANOERG_PER_ERG, {token_id: amount})

    def mint_token(self, name: str, description: str, amount: int, decimals: int) -> TransactionBuilder:
        """Mint a new native token (EIP-004 compliant).

        The token ID will be the ID of the first input box in the built transaction.
        The caller's wallet receives the minted tokens.
        """
        self._outputs.append({
            "type": "mint_token",
            "name": name,
            "description": description,
            "token_amount": amount,
            "decimals": decimals,
            "amount_nanoerg": MIN_BOX_VALUE_NANOERG,
        })
        return self

    def add_output_raw(
        self,
        ergo_tree: str,
        value_nanoerg: int,
        tokens: list[dict[str, Any]] | None = None,
        registers: dict[str, str | Constant] | None = None,
    ) -> TransactionBuilder:
        """Add a raw output box (for custom contract interactions like DEX swaps)."""
        resolved_registers = {}
        if registers:
            for k, v in registers.items():
                if isinstance(v, Constant):
                    resolved_registers[k] = bytes(v).hex()
                else:
                    resolved_registers[k] = v

        self._outputs.append({
            "type": "raw",
            "ergo_tree": ergo_tree,
            "amount_nanoerg": value_nanoerg,
            "tokens": tokens or [],
            "registers": resolved_registers,
        })
        return self

    def with_input(
        self,
        box: Box | str,
        extension: dict[str, str | Constant] | None = None,
    ) -> TransactionBuilder:
        """
        Add an explicit input box (for spending contract boxes like PoolBoxes).

        Args:
            box: a Box object or a box ID string. If a string, the box will
                 be fetched from the node when build() is called.
            extension: context extension variables for this input.
                       Keys are variable IDs (as strings, e.g. "0", "1"),
                       values are either serialized hex strings or native
                       `ergo_lib_python.chain.Constant` objects.
                       These correspond to getVar[T](id) calls in ErgoScript.

        Example:
            from ergo_lib_python.chain import Constant
            builder.with_input(pool_box, extension={
                "0": Constant.from_i64(100),
                "1": bytes(Constant(b"metadata")).hex(),  # manual hex works too
            })
        """
        resolved_extension = {}
        if extension:
            for k, v in extension.items():
                if isinstance(v, Constant):
                    resolved_extension[k] = bytes(v).hex()
                else:
                    resolved_extension[k] = v

        if isinstance(box, str):
            # Will be resolved at build() time
            self._explicit_inputs.append({
                "box_id": box,
                "box": None,
                "extension": resolved_extension,
            })
        else:
            self._explicit_inputs.append({
                "box_id": box.box_id,
                "box": box,
                "extension": resolved_extension,
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
        total_needed_erg = sum(o["amount_nanoerg"] for o in self._outputs) + self._fee_nanoerg

        # Calculate total tokens needed
        tokens_needed: dict[str, int] = {}
        for out in self._outputs:
            if out["type"] == "send_funds":
                for t_id, amt in out["tokens"].items():
                    tokens_needed[t_id] = tokens_needed.get(t_id, 0) + amt
            elif out["type"] == "raw" and "tokens" in out:
                for t in out["tokens"]:
                    tokens_needed[t["tokenId"]] = tokens_needed.get(t["tokenId"], 0) + t["amount"]

        # --- Resolve explicit inputs ---
        input_entries: list[dict[str, Any]] = []
        total_input_erg = 0
        total_input_tokens: dict[str, int] = {}
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
            total_input_erg += box.value
            for t in box.tokens:
                total_input_tokens[t.token_id] = total_input_tokens.get(t.token_id, 0) + t.amount
            explicit_box_ids.add(box.box_id)

        # --- Auto-select wallet UTXOs for the remainder (if needed) ---
        remaining_erg = max(0, total_needed_erg - total_input_erg)
        remaining_tokens: dict[str, int] = {}
        for t_id, needed_amt in tokens_needed.items():
            diff = needed_amt - total_input_tokens.get(t_id, 0)
            if diff > 0:
                remaining_tokens[t_id] = diff

        if remaining_erg > 0 or remaining_tokens:
            available_boxes = self._node.get_unspent_boxes(self._wallet.address)
            if not available_boxes:
                raise TransactionBuilderError(
                    f"No unspent boxes found for address {self._wallet.address}."
                )
            # Exclude any boxes already explicitly included
            available_boxes = [
                b for b in available_boxes if b.box_id not in explicit_box_ids
            ]
            selected, sel_erg, sel_tokens = self._select_boxes(available_boxes, remaining_erg, remaining_tokens)
            for b in selected:
                input_entries.append({
                    "boxId": b.box_id,
                    "spendingProof": {"proofBytes": "", "extension": {}},
                })
            total_input_erg += sel_erg
            for t_id, amt in sel_tokens.items():
                total_input_tokens[t_id] = total_input_tokens.get(t_id, 0) + amt

        # Compute change
        change_nanoerg = total_input_erg - total_needed_erg
        if change_nanoerg < 0:
            balance_erg = total_input_erg / NANOERG_PER_ERG
            needed_erg = total_needed_erg / NANOERG_PER_ERG
            raise TransactionBuilderError(
                f"Insufficient funds: have {balance_erg:.4f} ERG, need {needed_erg:.4f} ERG."
            )

        change_tokens: dict[str, int] = {}
        for t_id, input_amt in total_input_tokens.items():
            spent = tokens_needed.get(t_id, 0)
            change = input_amt - spent
            if change > 0:
                change_tokens[t_id] = change

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
                    "ergoTree": self._resolve_ergo_tree(out.get("address", self._wallet.address)),
                    "creationHeight": current_height,
                    "assets": [],
                    "additionalRegisters": {},
                }
                if out["type"] == "send_funds" and out["tokens"]:
                    box["assets"] = [
                        {"tokenId": t_id, "amount": amt} for t_id, amt in out["tokens"].items()
                    ]
                elif out["type"] == "mint_token":
                    if not input_entries:
                        raise TransactionBuilderError("Cannot mint a token without inputs (wallet is empty).")

                    new_token_id = input_entries[0]["boxId"]
                    box["assets"] = [{"tokenId": new_token_id, "amount": out["token_amount"]}]

                    box["additionalRegisters"] = {
                        "R4": bytes(Constant(out["name"].encode("utf-8"))).hex(),
                        "R5": bytes(Constant(out["description"].encode("utf-8"))).hex(),
                        "R6": bytes(Constant(str(out["decimals"]).encode("utf-8"))).hex()
                    }
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
        if change_nanoerg >= MIN_BOX_VALUE_NANOERG or change_tokens:
            if change_nanoerg < MIN_BOX_VALUE_NANOERG and change_nanoerg > 0:
                # We need a change box for tokens, but don't have enough ERG to satisfy Ergo box minimums.
                # A robust algorithm would select another UTXO box here. Fast fix: throw an error guiding the user.
                raise TransactionBuilderError("Insufficient ERG change to create a token change box. Send slightly less ERG or add more UTXOs.")

            change_assets = [{"tokenId": t_id, "amount": amt} for t_id, amt in change_tokens.items()]
            outputs.append({
                "value": change_nanoerg,
                "ergoTree": self._resolve_ergo_tree(self._wallet.address),
                "creationHeight": current_height,
                "assets": change_assets,
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
        self, available_boxes: list[Box], amount_needed_erg: int, tokens_needed: dict[str, int]
    ) -> tuple[list[Box], int, dict[str, int]]:
        """Greedy UTXO selection: pick boxes until we have enough ERG and tokens."""
        selected = []
        total_erg = 0
        total_tokens: dict[str, int] = {}

        # Sort boxes by ERG value descending for simple selection
        for box in sorted(available_boxes, key=lambda b: b.value, reverse=True):
            # Check if we still need anything
            erg_satisfied = total_erg >= amount_needed_erg
            tokens_satisfied = all(total_tokens.get(t_id, 0) >= needed for t_id, needed in tokens_needed.items())

            if erg_satisfied and tokens_satisfied:
                break

            selected.append(box)
            total_erg += box.value
            for t in box.tokens:
                total_tokens[t.token_id] = total_tokens.get(t.token_id, 0) + t.amount

        # Final check
        if total_erg < amount_needed_erg:
            raise TransactionBuilderError(f"Insufficient ERG: need {amount_needed_erg / NANOERG_PER_ERG:.4f}, have {total_erg / NANOERG_PER_ERG:.4f}")

        for t_id, needed in tokens_needed.items():
            if total_tokens.get(t_id, 0) < needed:
                raise TransactionBuilderError(f"Insufficient token {t_id}: need {needed}, have {total_tokens.get(t_id, 0)}")

        return selected, total_erg, total_tokens
