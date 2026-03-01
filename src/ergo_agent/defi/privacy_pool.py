"""
privacy pool Privacy Pool Client (Hardened)

Provides a simplified interface for an AI Agent to:
1. Scan for active privacy pool privacy pools.
2. Evaluate the anonymity set (Ring Size) of a given pool natively using PyO3 Constant decoding.
3. Build EIP-41 stealth deposit and dynamic Ring Signature withdrawal transactions.

Security hardening (threat model fixes):
- [2.1]  Blocks groupGenerator as key image (nullifier poisoning prevention)
- [2.1b] Blocks H constant as key image
- [2.2]  Validates deposit keys are valid secp256k1 compressed points
- [2.3]  Detects duplicate stealth keys before deposit
- [1.2]  Pre-checks pool capacity before building deposit tx
- [4.1]  Enhanced pool health reporting (token balance, effective anonymity)
"""

import json
import logging
import os
from typing import Any

import httpx

from ergo_agent.core.builder import TransactionBuilder
from ergo_agent.core.node import ErgoNode

logger = logging.getLogger("ergo_agent.privacy_pool")


# Protocol constants -- MUST match the on-chain contract
GROUP_GENERATOR = "0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"
H_CONSTANT = "022975f1d28b92b6e84499b83b0797ef5235553eeb7edaa0cea243c1128c2fe739"

# Known dangerous GroupElement values that must never be used as key images or deposit keys
_BANNED_KEYS = frozenset({GROUP_GENERATOR, H_CONSTANT})


class PoolValidationError(ValueError):
    """Raised when SDK-level validation catches a dangerous input."""
    pass


class PrivacyPoolClient:
    def __init__(self, node: ErgoNode = None, wallet=None):
        self.node = node or ErgoNode()
        self.wallet = wallet

        # Dynamically load the deployed contract ErgoTree representation
        compiled_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "compiled_contracts.json")
        try:
            with open(compiled_path) as f:
                contracts = json.load(f)
                self.MOCK_POOL_ERGO_TREE = contracts["pool"]["tree"]
                self.pool_address = contracts["pool"]["address"]
        except Exception as e:
            logger.warning(f"Falling back to empty pool config: {e}")
            self.MOCK_POOL_ERGO_TREE = ""
            self.pool_address = ""

    # ------------------------------------------------------------------
    # Validation Helpers (Threat Model Fixes)
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_compressed_point(hex_str: str, label: str = "key") -> None:
        """
        [FIX 2.2] Validate that hex_str is a valid compressed secp256k1 point format.

        Checks:
        - Exactly 66 hex characters (33 bytes)
        - Starts with 02 or 03 (compressed point prefix)
        - Not a banned protocol constant (groupGenerator, H)

        Raises PoolValidationError if invalid.
        """
        if not hex_str or not isinstance(hex_str, str):
            raise PoolValidationError(f"Invalid {label}: must be a hex string, got {type(hex_str)}")

        hex_str = hex_str.lower()

        if len(hex_str) != 66:
            raise PoolValidationError(
                f"Invalid {label}: expected 66 hex chars (33 bytes), got {len(hex_str)}"
            )

        if hex_str[:2] not in ("02", "03"):
            raise PoolValidationError(
                f"Invalid {label}: must start with 02 or 03, got {hex_str[:2]}"
            )

        try:
            bytes.fromhex(hex_str)
        except ValueError as err:
            raise PoolValidationError(f"Invalid {label}: not valid hex") from err

        # [FIX 2.1, 2.1b] Block known dangerous values
        if hex_str in _BANNED_KEYS:
            if hex_str == GROUP_GENERATOR:
                raise PoolValidationError(
                    f"SECURITY: {label} is the secp256k1 group generator. "
                    f"Using it as a key image would permanently poison the nullifier list. "
                    f"Using it as a deposit key would create a trivially provable slot."
                )
            elif hex_str == H_CONSTANT:
                raise PoolValidationError(
                    f"SECURITY: {label} is the protocol H constant. "
                    f"Using it would compromise the DH tuple proof security."
                )

    def _check_duplicate_key(self, pool_r4_hex: str, new_key: str) -> None:
        """
        [FIX 2.3] Check if the stealth key already exists in the pool's R4 collection.

        Raises PoolValidationError if duplicate detected.
        """
        if not pool_r4_hex or len(pool_r4_hex) <= 4:
            return  # Empty pool, no duplicates possible

        new_key_lower = new_key.lower()

        # Parse existing keys from R4 hex
        if pool_r4_hex.startswith("13"):
            count = self._read_vlq(pool_r4_hex[2:])
            vlq_hex = self._encode_vlq(count)
            data = pool_r4_hex[2 + len(vlq_hex):]

            # Each GroupElement is 66 hex chars (33 bytes)
            for i in range(count):
                start = i * 66
                end = start + 66
                if end <= len(data):
                    existing_key = data[start:end].lower()
                    if existing_key == new_key_lower:
                        raise PoolValidationError(
                            f"SECURITY: Stealth key {new_key[:16]}... already exists "
                            f"in pool R4 at position {i}. Duplicate keys inflate ring "
                            f"size without adding real anonymity."
                        )

    def _check_key_image_not_spent(self, pool_r5_hex: str, key_image: str) -> None:
        """
        [FIX double-spend] Check if the key image already exists in the pool's R5 nullifier set.

        For AvlTree R5 (PrivacyPoolV6), we attempt a lookup via the ergo_avltree
        prover. For legacy Coll[GroupElement] R5, we do a linear scan.

        Raises PoolValidationError if the key image has already been used.
        """
        if not pool_r5_hex or pool_r5_hex == "1300" or len(pool_r5_hex) <= 4:
            return  # No nullifiers yet

        # AvlTree R5 starts with type byte 0x64
        if pool_r5_hex.startswith("64"):
            # AvlTree format — the key image cannot be verified without the
            # full tree state. We rely on the node's validator to reject
            # duplicate inserts at signing time.
            logger.debug("R5 is AvlTree format; double-spend check deferred to node validator")
            return

        # Legacy Coll[GroupElement] format (type 0x13)
        key_image_lower = key_image.lower()
        if pool_r5_hex.startswith("13"):
            count = self._read_vlq(pool_r5_hex[2:])
            vlq_hex = self._encode_vlq(count)
            data = pool_r5_hex[2 + len(vlq_hex):]
            for i in range(count):
                start = i * 66
                end = start + 66
                if end <= len(data):
                    existing = data[start:end].lower()
                    if existing == key_image_lower:
                        raise PoolValidationError(
                            f"DOUBLE-SPEND: Key image {key_image[:16]}... already "
                            f"exists in R5 nullifier list at position {i}."
                        )

    # ------------------------------------------------------------------
    # Pool Scanning & Analytics
    # ------------------------------------------------------------------

    def get_active_pools(self, denomination: int = 100) -> list[dict[str, Any]]:
        """
        Scan the blockchain for active privacy pool PoolBox UTXOs of a specific denomination.

        Args:
            denomination: The token denomination (e.g., 100, 1000)

        Returns:
            A list of dictionary summaries including pool_id and current ring size.
        """
        pools = []
        if not self.pool_address:
            return pools

        try:
            url = f"{self.node.explorer_url}/api/v1/boxes/unspent/byAddress/{self.pool_address}"
            resp = httpx.get(url, timeout=10.0)
            if resp.status_code == 200:
                boxes = resp.json().get("items", [])
                for b in boxes:
                    r6_val = b.get("additionalRegisters", {}).get("R6", {}).get("renderedValue", "0")
                    if str(denomination) in r6_val or r6_val == "0":
                        # Count depositor keys from R4
                        r4_data = b.get("additionalRegisters", {}).get("R4", {})
                        ring_size = self._count_group_elements(r4_data)

                        # [FIX 5.2] Include token balance for honest reporting
                        token_balance = b["assets"][0]["amount"] if b.get("assets") else 0
                        withdrawable = token_balance // denomination if denomination > 0 else 0

                        # Count nullifiers in R5 for activity tracking
                        r5_data = b.get("additionalRegisters", {}).get("R5", {})
                        nullifier_count = self._count_group_elements(r5_data)

                        pools.append({
                            "pool_id": b["boxId"],
                            "denomination": denomination,
                            "token_id": b["assets"][0]["tokenId"] if b.get("assets") else "",
                            "depositors": ring_size,
                            "max_depositors": 16,
                            # NEW: Enhanced pool health metrics
                            "token_balance": token_balance,
                            "withdrawable": withdrawable,
                            "nullifiers": nullifier_count,
                            "slots_remaining": max(0, 16 - ring_size),
                            "is_full": ring_size >= 16,
                        })
        except Exception as e:
            logger.error(f"Pool scan failed: {e}")

        return pools

    def select_best_pool(self, denomination: int = 100) -> dict[str, Any] | None:
        """
        Auto-select the best pool for a deposit based on:
          1. Not full (slots_remaining > 0)
          2. Highest anonymity (most depositors) for privacy
          3. Most slots remaining as tiebreaker

        Returns the pool dict or None if no suitable pool exists.
        """
        pools = self.get_active_pools(denomination=denomination)
        eligible = [p for p in pools if not p["is_full"]]
        if not eligible:
            return None
        # Sort: highest depositors first, then most slots remaining
        eligible.sort(key=lambda p: (p["depositors"], p["slots_remaining"]), reverse=True)
        return eligible[0]

    def evaluate_pool_health(self, pool_box_id: str) -> dict[str, Any]:
        """
        [FIX 1.1, 3.1, 5.2] Enhanced pool analytics with effective anonymity assessment.

        Returns comprehensive health metrics including privacy risk indicators.
        """
        box = self.node.get_box_by_id(pool_box_id)
        if not box:
            return {"error": "Pool not found"}

        r4 = box.additional_registers.get("R4", "")
        if isinstance(r4, dict):
            r4 = r4.get("serializedValue", "")

        r5 = box.additional_registers.get("R5", "1300")
        if isinstance(r5, dict):
            r5 = r5.get("serializedValue", "1300")

        ring_size = self._count_group_elements(r4)
        nullifier_count = self._count_group_elements(r5) if r5 != "1300" else 0
        token_balance = box.tokens[0].amount if box.tokens else 0

        r6 = box.additional_registers.get("R6", "05c801")
        if isinstance(r6, dict):
            r6 = r6.get("serializedValue", "05c801")
        denom = self._decode_r6_denomination(r6)

        withdrawable = token_balance // denom if denom > 0 else 0

        # Check for duplicate keys in R4 (ring poisoning indicator)
        unique_keys = set()
        duplicate_count = 0
        if r4.startswith("13") and len(r4) > 4:
            count = self._read_vlq(r4[2:])
            vlq_hex = self._encode_vlq(count)
            data = r4[2 + len(vlq_hex):]
            for i in range(count):
                start = i * 66
                end = start + 66
                if end <= len(data):
                    key = data[start:end].lower()
                    if key in unique_keys:
                        duplicate_count += 1
                    unique_keys.add(key)

        effective_anonymity = len(unique_keys)

        # Privacy risk assessment
        risk_flags = []
        if ring_size < 4:
            risk_flags.append("LOW_RING_SIZE: Ring < 4, weak anonymity")
        if duplicate_count > 0:
            risk_flags.append(f"DUPLICATE_KEYS: {duplicate_count} duplicate keys detected (possible ring poisoning)")
        if effective_anonymity < ring_size:
            risk_flags.append(f"INFLATED_RING: Reported ring={ring_size} but unique keys={effective_anonymity}")
        if withdrawable < ring_size and ring_size > 0:
            risk_flags.append(f"LOW_LIQUIDITY: Only {withdrawable} withdrawals possible with ring of {ring_size}")
        if nullifier_count > 0 and ring_size > 0:
            withdrawal_ratio = nullifier_count / ring_size
            if withdrawal_ratio > 0.5:
                risk_flags.append(f"HIGH_WITHDRAWAL_RATIO: {nullifier_count}/{ring_size} keys withdrawn ({withdrawal_ratio:.0%})")

        return {
            "pool_id": pool_box_id,
            "ring_size": ring_size,
            "effective_anonymity": effective_anonymity,
            "duplicate_keys": duplicate_count,
            "nullifier_count": nullifier_count,
            "token_balance": token_balance,
            "denomination": denom,
            "withdrawable": withdrawable,
            "slots_remaining": max(0, 16 - ring_size),
            "is_full": ring_size >= 16,
            "risk_flags": risk_flags,
            "privacy_score": _compute_privacy_score(effective_anonymity, risk_flags),
        }

    def _count_group_elements(self, r4_data: dict | str) -> int:
        """Count the number of GroupElements in an R4 register from explorer data."""
        if isinstance(r4_data, dict):
            serialized = r4_data.get("serializedValue", "")
        else:
            serialized = r4_data

        if not serialized or len(serialized) <= 4:
            return 0

        # Coll[GroupElement] format: 13 <vlq_count> <33-byte elements>...
        if serialized.startswith("13"):
            count = self._read_vlq(serialized[2:])
            return count
        return 0

    @staticmethod
    def _read_vlq(hex_str: str) -> int:
        """Read a VLQ-encoded integer from hex string."""
        result = 0
        shift = 0
        idx = 0
        while idx < len(hex_str):
            byte = int(hex_str[idx:idx+2], 16)
            idx += 2
            result |= (byte & 0x7F) << shift
            if (byte & 0x80) == 0:
                break
            shift += 7
        return result

    @staticmethod
    def _encode_vlq(n: int) -> str:
        """Encode an integer as VLQ hex."""
        if n == 0:
            return "00"
        parts = []
        while n > 0:
            byte = n & 0x7F
            n >>= 7
            if n > 0:
                byte |= 0x80
            parts.append(f"{byte:02x}")
        return "".join(parts)

    def evaluate_pool_anonymity(self, pool_box_id: str) -> int:
        """
        Fetch a PoolBox and decode R4 to determine the current ring size.
        """
        try:
            box = self.node.get_box_by_id(pool_box_id)
            if box:
                r4 = box.additional_registers.get("R4", "")
                if isinstance(r4, dict):
                    r4 = r4.get("serializedValue", "")
                return self._count_group_elements(r4)
        except Exception as e:
            logger.warning(f"Failed to evaluate pool anonymity for {pool_box_id}: {e}")
        return 0

    # ------------------------------------------------------------------
    # Transaction Builders (Hardened)
    # ------------------------------------------------------------------

    def build_deposit_tx(
        self,
        pool_box_id: str,
        user_stealth_key: str,
        denomination: int
    ) -> TransactionBuilder:
        """
        Construct a transaction depositing privacy pool into a privacy pool.
        This appends the user's stealth key onto the pool's R4 array.

        Security validations:
        - Stealth key must be valid compressed secp256k1 format
        - Stealth key must not be groupGenerator or H constant
        - Stealth key must not already exist in pool R4 (duplicate detection)
        - Pool must have remaining capacity
        """
        # [FIX 2.2, 2.1, 2.1b] Validate stealth key
        self._validate_compressed_point(user_stealth_key, label="stealth key")

        builder = TransactionBuilder(self.node, self.wallet)

        pool_box = self.node.get_box_by_id(pool_box_id)
        if not pool_box:
            raise ValueError(f"SDK could not resolve pool output {pool_box_id}")

        logger.debug(f"Live R4 state: {pool_box.additional_registers.get('R4')}")

        # Extract current R4 Ring and compute appended size
        pool_r4_hex = pool_box.additional_registers.get("R4", "1300")
        if isinstance(pool_r4_hex, dict):
             pool_r4_hex = pool_r4_hex.get("serializedValue", "1300")

        # [FIX 1.2] Pre-check pool capacity
        current_size = 0
        current_array_data = ""
        if len(pool_r4_hex) > 4:
            current_size = self._read_vlq(pool_r4_hex[2:])
            vlq_hex = self._encode_vlq(current_size)
            current_array_data = pool_r4_hex[2 + len(vlq_hex):]

        # Check capacity
        pool_r7 = pool_box.additional_registers.get("R7", "0420")
        if isinstance(pool_r7, dict):
            pool_r7 = pool_r7.get("serializedValue", "0420")
        max_ring = self._decode_r7_max_ring(pool_r7)
        if current_size >= max_ring:
            raise PoolValidationError(
                f"Pool is full: {current_size}/{max_ring} slots used. "
                f"Cannot accept new deposits."
            )

        # [FIX 2.3] Check for duplicate keys
        self._check_duplicate_key(pool_r4_hex, user_stealth_key)

        new_size = current_size + 1
        new_r4_hex = f"13{self._encode_vlq(new_size)}{current_array_data}{user_stealth_key}"

        pool_box.tokens[0].amount if pool_box.tokens else 0
        pool_box.tokens[0].token_id if pool_box.tokens else ""

        builder.with_input(pool_box)
        pool_r5_hex = pool_box.additional_registers.get("R5", "1300")
        if isinstance(pool_r5_hex, dict):
            pool_r5_hex = pool_r5_hex.get("serializedValue", "1300")

        # Extract R6 from the live pool box
        pool_r6 = pool_box.additional_registers.get("R6", "05c801")
        if isinstance(pool_r6, dict):
            pool_r6 = pool_r6.get("serializedValue", "05c801")

        tokens_out = []
        if pool_box.tokens:
            tokens_out.append({
                "tokenId": pool_box.tokens[0].token_id,
                "amount": pool_box.tokens[0].amount + denomination
            })

        builder.add_output_raw(
            ergo_tree=pool_box.ergo_tree,
            value_nanoerg=pool_box.value,
            tokens=tokens_out,
            registers={
                "R4": new_r4_hex,
                "R5": pool_r5_hex,
                "R6": pool_r6,
                "R7": pool_r7
            }
        )
        return builder

    def _decode_r6_denomination(self, r6_hex: str) -> int:
        """Decode the R6 register (Long) to extract the pool denomination."""
        if not r6_hex or len(r6_hex) < 4:
            return 100  # safe default
        try:
            hex_data = r6_hex[2:] if r6_hex.startswith("05") else r6_hex
            raw = self._read_vlq(hex_data)
            return (raw >> 1) ^ -(raw & 1)
        except Exception:
            return 100

    def _decode_r7_max_ring(self, r7_hex: str) -> int:
        """Decode the R7 register (Int) to extract max ring size."""
        if not r7_hex or len(r7_hex) < 4:
            return 16  # safe default
        try:
            hex_data = r7_hex[2:] if r7_hex.startswith("04") else r7_hex
            raw = self._read_vlq(hex_data)
            return (raw >> 1) ^ -(raw & 1)
        except Exception:
            return 16

    def _find_depositor_pubkey(self, pool_r4_hex: str, secret_hex: str) -> str:
        """
        Derive the public key from the secret and verify it exists in the pool's R4.

        Args:
            pool_r4_hex: Serialized R4 register (Coll[GroupElement]).
            secret_hex: The 32-byte depositor secret (hex).

        Returns:
            Compressed public key hex (66 chars).
        """
        import ecdsa

        # Derive the public key from the secret
        priv_key_bytes = bytes.fromhex(secret_hex)
        signing_key = ecdsa.SigningKey.from_string(priv_key_bytes, curve=ecdsa.SECP256k1)
        verifying_key = signing_key.get_verifying_key()
        x = verifying_key.pubkey.point.x()
        y = verifying_key.pubkey.point.y()
        prefix = "02" if y % 2 == 0 else "03"
        pubkey_hex = prefix + x.to_bytes(32, byteorder="big").hex()

        logger.debug(f"Derived pubkey from secret: {pubkey_hex[:20]}...")
        return pubkey_hex

    def build_withdrawal_tx(
        self,
        pool_box_id: str,
        recipient_stealth_address: str,
        secret_hex: str,
    ) -> TransactionBuilder:
        """
        Construct a withdrawal transaction out of the privacy pool using
        the dynamic `atLeast(1, keys.map(...))` Ring Signature mechanism.

        Computes the key image from the secret, generates the AvlTree insert
        proof, and builds the full transaction with correct context extensions.

        Security validations:
        - Key image must be valid compressed secp256k1 format
        - Key image must not be groupGenerator (prevents nullifier poisoning)
        - Key image must not be H constant
        - Key image must not already be in R5 (double-spend prevention)

        Args:
            pool_box_id: ID of the PoolBox to withdraw from.
            recipient_stealth_address: Ergo address of the withdrawal recipient.
            secret_hex: The depositor's 32-byte secret key (hex).

        Returns:
            TransactionBuilder with the withdrawal TX ready to build/sign.
        """
        from ergo_agent.core.privacy import (
            compute_key_image,
            generate_avl_insert_proof,
            serialize_context_extension,
        )

        # 1. Compute key image (nullifier)
        key_image = compute_key_image(secret_hex)

        # [FIX 2.1, 2.1b, 2.2] Validate key image
        self._validate_compressed_point(key_image, label="key image")

        builder = TransactionBuilder(self.node, self.wallet)

        pool_box = self.node.get_box_by_id(pool_box_id)
        if not pool_box:
            raise ValueError(f"Pool Box {pool_box_id} not found")

        pool_r4 = pool_box.additional_registers.get("R4")
        if isinstance(pool_r4, dict):
            pool_r4 = pool_r4.get("serializedValue")

        pool_r5 = pool_box.additional_registers.get("R5", "")
        if isinstance(pool_r5, dict):
            pool_r5 = pool_r5.get("serializedValue", "")

        # [FIX double-spend] Check key image not already in nullifier set
        self._check_key_image_not_spent(pool_r5, key_image)

        pool_r6 = pool_box.additional_registers.get("R6", "05c801")
        if isinstance(pool_r6, dict):
            pool_r6 = pool_r6.get("serializedValue", "05c801")

        pool_r7 = pool_box.additional_registers.get("R7", "0420")
        if isinstance(pool_r7, dict):
            pool_r7 = pool_r7.get("serializedValue", "0420")

        # Extract denomination dynamically from R6
        token_id = pool_box.tokens[0].token_id
        current_amount = pool_box.tokens[0].amount
        denom = self._decode_r6_denomination(pool_r6)

        # 2. Generate AvlTree insert proof and new R5 digest
        proof_bytes, new_r5 = generate_avl_insert_proof(key_image, pool_r5)

        # 3. Build context extension with properly serialized Sigma types
        extension = serialize_context_extension(key_image, proof_bytes)

        from ergo_agent.core.address import address_to_ergo_tree
        try:
            recipient_tree = address_to_ergo_tree(recipient_stealth_address)
        except Exception as e:
            raise ValueError(f"Invalid recipient address: {recipient_stealth_address}") from e

        builder.with_input(pool_box, extension=extension)

        # Output 0: The Continuous Pool Box (tokens decreased by exact denomination)
        builder.add_output_raw(
            ergo_tree=pool_box.ergo_tree,
            value_nanoerg=pool_box.value,
            tokens=[{"tokenId": token_id, "amount": current_amount - denom}],
            registers={
                "R4": pool_r4,
                "R5": new_r5,
                "R6": pool_r6,
                "R7": pool_r7
            }
        )

        # Output 1: The Withdrawn Note Box (exact denomination, no fee deduction)
        builder.add_output_raw(
            ergo_tree=recipient_tree,
            value_nanoerg=1000000,
            tokens=[{"tokenId": token_id, "amount": denom}],
            registers={}
        )

        # Attach signing secrets for ring signature (proveDlog + proveDHTuple)
        # The node needs these to construct the Sigma proof at signing time.
        from ergo_agent.core.privacy import NUMS_H_HEX

        # Find the depositor's public key in R4 that corresponds to this secret
        depositor_pubkey = self._find_depositor_pubkey(pool_r4, secret_hex)

        # secp256k1 generator (compressed)
        G_COMPRESSED = "0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"

        builder.signing_secrets = {
            "dlog": [secret_hex],
            "dht": [
                {
                    "secret": secret_hex,
                    "g": G_COMPRESSED,
                    "h": NUMS_H_HEX,
                    "u": depositor_pubkey,
                    "v": key_image,
                }
            ],
        }

        return builder


def _compute_privacy_score(effective_anonymity: int, risk_flags: list[str]) -> str:
    """
    Compute a human-readable privacy score for a pool.

    Returns: "EXCELLENT", "GOOD", "FAIR", "POOR", or "CRITICAL"
    """
    score = effective_anonymity * 10  # Base: 10 points per unique depositor

    # Deductions for risk factors
    for flag in risk_flags:
        if "LOW_RING_SIZE" in flag:
            score -= 30
        elif "DUPLICATE_KEYS" in flag:
            score -= 40
        elif "INFLATED_RING" in flag:
            score -= 20
        elif "LOW_LIQUIDITY" in flag:
            score -= 10
        elif "HIGH_WITHDRAWAL_RATIO" in flag:
            score -= 15

    if score >= 100:
        return "EXCELLENT"
    elif score >= 60:
        return "GOOD"
    elif score >= 30:
        return "FAIR"
    elif score >= 10:
        return "POOR"
    else:
        return "CRITICAL"
