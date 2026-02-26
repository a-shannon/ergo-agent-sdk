"""
privacy pool Privacy Client (v7) — User-Facing SDK for the privacy pool Protocol.

Provides a high-level API for:
  1. Creating deposit intents (IntentToDeposit boxes)
  2. Building withdrawal proofs (DHTuple ring signatures)
  3. Creating withdrawal intents (IntentToWithdraw boxes)
  4. Managing private keys (blinding factors) and view keys
  5. Scanning for active MasterPoolBoxes and assessing anonymity set quality

Architecture:
    User → PrivacyPoolClient → creates IntentToDeposit/IntentToWithdraw boxes
    Relayer → picks up intents → batches into MasterPoolBox transactions

    The user never touches the MasterPoolBox directly. The PrivacyPoolClient
    creates intent boxes that relayers sweep permissionlessly.

Dependencies:
    - ergo_agent.crypto: Pedersen commitments, DHTuple ring signatures
    - ergo_agent.relayer.pool_deployer: Tier configs
    - ergo_agent.core.node: Ergo node connection (for scanning)
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from typing import Any

from ergo_agent.crypto.pedersen import (
    G_COMPRESSED,
    NUMS_H,
    SECP256K1_N,
    PedersenCommitment,
    decode_point,
    encode_point,
)
from ergo_agent.crypto.dhtuple import (
    build_withdrawal_ring,
    compute_nullifier,
    generate_secondary_generator,
    verify_nullifier,
)
from ergo_agent.relayer.pool_deployer import (
    NANOERG,
    POOL_TIERS,
    MIN_BOX_VALUE,
)


# ==============================================================================
# Data Classes
# ==============================================================================


@dataclass(frozen=True)
class DepositSecret:
    """
    A deposit secret — the user's private key for a deposit.

    The blinding factor `r` is the critical secret. It is used to:
    - Create the Pedersen Commitment C = r·G + amount·H
    - Construct the withdrawal DHTuple proof
    - Act as a View Key for compliance disclosure

    SECURITY: This must be stored securely. Loss = loss of funds.
              Disclosure = loss of privacy (View Key).
    """
    blinding_factor: int
    """The random blinding factor r ∈ [1, N-1]."""

    commitment_hex: str
    """The Pedersen Commitment C = r·G + amount·H (66-char hex)."""

    amount: int
    """The deposited amount in nanoERG."""

    tier: str
    """The pool tier name (e.g., '1_erg', '10_erg', '100_erg')."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict (for encrypted storage)."""
        return {
            "r": hex(self.blinding_factor),
            "C": self.commitment_hex,
            "amount": self.amount,
            "tier": self.tier,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DepositSecret:
        """Deserialize from a dict."""
        return cls(
            blinding_factor=int(d["r"], 16),
            commitment_hex=d["C"],
            amount=d["amount"],
            tier=d["tier"],
        )


@dataclass(frozen=True)
class WithdrawalProof:
    """
    A withdrawal proof — everything needed to create an IntentToWithdraw box.

    Contains the DHTuple ring signature, nullifier, secondary generator,
    and payout destination.
    """
    nullifier_hex: str
    """Key Image I = r·U (66-char hex)."""

    secondary_gen_hex: str
    """Secondary generator U (66-char hex, random per withdrawal)."""

    payout_ergo_tree: str
    """ErgoTree of the payout destination address."""

    ring_size: int
    """Number of commitments in the ring (including real)."""

    ring_data: dict[str, Any]
    """Full ring signature data for the Sigma proof."""


# ==============================================================================
# privacy pool Client
# ==============================================================================


class PrivacyPoolClient:
    """
    User-facing SDK client for the privacy pool privacy protocol.

    Usage:
        client = PrivacyPoolClient()

        # Deposit
        secret = client.create_deposit("10_erg")
        intent_box = client.build_deposit_intent(secret, user_ergo_tree)

        # Withdraw (after relayer sweeps the deposit)
        decoys = client.fetch_decoy_commitments(pool_box, count=7)
        proof = client.build_withdrawal_proof(secret, decoys, payout_ergo_tree)
        withdraw_box = client.build_withdrawal_intent(proof)
    """

    def __init__(self, node=None):
        """
        Initialize the privacy pool client.

        Args:
            node: Optional ErgoNode instance for on-chain queries.
                  If None, only offline operations are available.
        """
        self.node = node

    # ------------------------------------------------------------------
    # Deposit Operations
    # ------------------------------------------------------------------

    def create_deposit(self, tier: str) -> DepositSecret:
        """
        Generate a fresh deposit secret for a given pool tier.

        Creates a random blinding factor and computes the Pedersen Commitment.
        The returned DepositSecret must be stored securely by the user —
        it is the only way to later withdraw the funds.

        Args:
            tier: Pool tier name ('1_erg', '10_erg', or '100_erg').

        Returns:
            A DepositSecret containing the blinding factor and commitment.

        Raises:
            ValueError: If the tier is unknown.
        """
        if tier not in POOL_TIERS:
            raise ValueError(f"Unknown tier: {tier}. Available: {list(POOL_TIERS.keys())}")

        denom = POOL_TIERS[tier]["denomination"]

        # Generate a cryptographically random blinding factor
        r = secrets.randbelow(SECP256K1_N - 1) + 1

        # Compute commitment C = r·G + amount·H
        C = PedersenCommitment.commit(r, denom)

        return DepositSecret(
            blinding_factor=r,
            commitment_hex=C,
            amount=denom,
            tier=tier,
        )

    def build_deposit_intent(
        self,
        secret: DepositSecret,
        depositor_ergo_tree: str,
    ) -> dict[str, Any]:
        """
        Build an IntentToDeposit box specification.

        The generated box contains:
          - Value: denomination amount (in nanoERG)
          - R4: Pedersen Commitment (GroupElement)
          - R5: Depositor's proveDlog (for timeout refund)

        This box is submitted to the Ergo mempool. A relayer will
        sweep it into the MasterPoolBox within ~1-10 blocks.

        Args:
            secret: The DepositSecret from create_deposit().
            depositor_ergo_tree: ErgoTree of the depositor's wallet
                                 (used for timeout refund).

        Returns:
            Box specification dict ready for TransactionBuilder.
        """
        # The commitment as a GroupElement register value
        # Sigma type 0x07 = GroupElement, followed by 33 compressed bytes
        commitment_register = "07" + secret.commitment_hex

        # proveDlog for the depositor (timeout refund path)
        # The depositor's ergo_tree is already a valid proposition
        depositor_register = depositor_ergo_tree

        return {
            "ergo_tree": None,  # Will be set to IntentToDeposit contract
            "value": secret.amount + MIN_BOX_VALUE,  # denom + min box value for fees
            "assets": [],
            "registers": {
                "R4": commitment_register,
                "R5": depositor_register,
            },
            "meta": {
                "type": "IntentToDeposit",
                "tier": secret.tier,
                "commitment": secret.commitment_hex,
            },
        }

    # ------------------------------------------------------------------
    # Withdrawal Operations
    # ------------------------------------------------------------------

    def build_withdrawal_proof(
        self,
        secret: DepositSecret,
        decoy_commitments: list[str],
        payout_ergo_tree: str,
    ) -> WithdrawalProof:
        """
        Build a withdrawal proof using DHTuple ring signatures.

        Constructs a ring over the real commitment and decoy commitments
        from the MasterPoolBox deposit tree. The proof demonstrates
        knowledge of the blinding factor for one of the ring members
        without revealing which one.

        Args:
            secret: The DepositSecret for the deposit being withdrawn.
            decoy_commitments: List of decoy commitment hex strings
                               from the MasterPoolBox deposit tree.
                               Should be at least 3 for reasonable privacy.
            payout_ergo_tree: ErgoTree of the payout destination address.

        Returns:
            A WithdrawalProof ready to be submitted as IntentToWithdraw.

        Raises:
            ValueError: If the ring construction fails (integrity check).
        """
        # Generate a fresh secondary generator U for this withdrawal
        U = generate_secondary_generator()

        # Compute nullifier I = r·U
        I = compute_nullifier(secret.blinding_factor, U)

        # Build the DHTuple ring
        ring = build_withdrawal_ring(
            blinding_factor=secret.blinding_factor,
            amount=secret.amount,
            real_commitment_hex=secret.commitment_hex,
            decoy_commitment_hexes=decoy_commitments,
        )

        return WithdrawalProof(
            nullifier_hex=I,
            secondary_gen_hex=U,
            payout_ergo_tree=payout_ergo_tree,
            ring_size=ring.ring_size,
            ring_data={
                "real_index": ring.real_index,
                "commitments": ring.ring_commitments,
                "opened_points": ring.opened_points,
                "secondary_gen": U,
                "nullifier": I,
            },
        )

    def build_withdrawal_intent(
        self,
        proof: WithdrawalProof,
    ) -> dict[str, Any]:
        """
        Build an IntentToWithdraw box specification.

        The generated box contains:
          - R4: Nullifier I (GroupElement)
          - R5: Secondary generator U (GroupElement)
          - R6: Payout address (proposition bytes)
          - R7: Ring data (for the Sigma proof)

        This box is submitted to the Ergo mempool. A relayer will
        process it (exactly one at a time) and execute the withdrawal.

        Args:
            proof: The WithdrawalProof from build_withdrawal_proof().

        Returns:
            Box specification dict ready for TransactionBuilder.
        """
        return {
            "ergo_tree": None,  # Will be set to IntentToWithdraw contract
            "value": MIN_BOX_VALUE,
            "assets": [],
            "registers": {
                "R4": "07" + proof.nullifier_hex,
                "R5": "07" + proof.secondary_gen_hex,
                "R6": proof.payout_ergo_tree,
            },
            "meta": {
                "type": "IntentToWithdraw",
                "ring_size": proof.ring_size,
                "nullifier": proof.nullifier_hex,
            },
        }

    # ------------------------------------------------------------------
    # View Key (Compliance / Selective Disclosure)
    # ------------------------------------------------------------------

    @staticmethod
    def export_view_key(secret: DepositSecret) -> dict[str, str]:
        """
        Export a View Key for compliance/audit disclosure.

        The blinding factor r acts as a View Key:
        - An auditor can verify (C - amount·H) == r·G on-chain
        - This proves the exact deposit amount without ZK ceremony

        Args:
            secret: The DepositSecret to export the view key for.

        Returns:
            Dict with the view key data for an auditor.
        """
        # Compute r·G (the opened commitment)
        rG = PedersenCommitment.open(secret.commitment_hex, secret.amount)

        return {
            "blinding_factor_hex": hex(secret.blinding_factor),
            "commitment": secret.commitment_hex,
            "amount_nanoerg": secret.amount,
            "opened_rG": rG,
            "verification": "Verify: (C - amount·H) == r·G using proveDlog",
        }

    @staticmethod
    def verify_view_key(
        commitment_hex: str,
        blinding_factor: int,
        amount: int,
    ) -> bool:
        """
        Verify a View Key disclosure (for auditors).

        Checks that C == r·G + amount·H.

        Args:
            commitment_hex: The Pedersen Commitment to verify.
            blinding_factor: The disclosed blinding factor r.
            amount: The disclosed amount in nanoERG.

        Returns:
            True if the disclosure is valid.
        """
        return PedersenCommitment.verify(commitment_hex, blinding_factor, amount)

    # ------------------------------------------------------------------
    # Bearer Note Transfer (Trusted)
    # ------------------------------------------------------------------

    @staticmethod
    def export_bearer_note(secret: DepositSecret) -> dict[str, Any]:
        """
        Export a Bearer Note for off-chain trusted transfer.

        The recipient receives:
        - The blinding factor r
        - The commitment C
        - The pool tier

        With r, the recipient can build a withdrawal proof and withdraw
        to their own address. This is an instant, zero-fee transfer
        but requires trust (Alice could front-run Bob's withdrawal).

        Args:
            secret: The DepositSecret to transfer.

        Returns:
            Bearer note data for the recipient.
        """
        return {
            "type": "privacy_bearer_note",
            "version": 1,
            "blinding_factor": hex(secret.blinding_factor),
            "commitment": secret.commitment_hex,
            "amount": secret.amount,
            "tier": secret.tier,
            "warning": "TRUSTED TRANSFER: sender can front-run withdrawal",
        }

    @staticmethod
    def import_bearer_note(note: dict[str, Any]) -> DepositSecret:
        """
        Import a Bearer Note received from another party.

        Args:
            note: The bearer note data.

        Returns:
            A DepositSecret that can be used to withdraw.

        Raises:
            ValueError: If the note is invalid or the commitment doesn't match.
        """
        if note.get("type") != "privacy_bearer_note":
            raise ValueError("Invalid bearer note format")

        r = int(note["blinding_factor"], 16)
        amount = note["amount"]
        expected_C = PedersenCommitment.commit(r, amount)

        if expected_C != note["commitment"]:
            raise ValueError(
                "Bearer note integrity check failed: "
                "commitment doesn't match (r, amount)"
            )

        return DepositSecret(
            blinding_factor=r,
            commitment_hex=note["commitment"],
            amount=amount,
            tier=note["tier"],
        )

    # ------------------------------------------------------------------
    # Pool Scanning (requires node connection)
    # ------------------------------------------------------------------

    def get_pool_status(self, pool_box_id: str) -> dict[str, Any]:
        """
        Query the current status of a MasterPoolBox.

        Args:
            pool_box_id: The box ID of the MasterPoolBox.

        Returns:
            Dict with pool status including deposit count,
            privacy score, anonymity assessment, and balance.

        Raises:
            RuntimeError: If no node connection is available.
        """
        if self.node is None:
            raise RuntimeError("Node connection required for pool scanning")

        box = self.node.get_box(pool_box_id)

        # Decode registers
        counter = self._decode_sigma_long(box["additionalRegisters"].get("R6", "0500"))
        denom = self._decode_sigma_long(box["additionalRegisters"].get("R7", "0500"))

        # Run client-side anonymity analysis
        try:
            from ergo_agent.core.privacy import analyze_anonymity_set
            assessment = analyze_anonymity_set(
                node_url=self.node.url,
                pool_box_id=pool_box_id,
                api_key=getattr(self.node, 'api_key', 'hello'),
            )
            privacy_data = {
                "privacy_score": assessment.privacy_score,
                "risk_level": assessment.risk_level,
                "is_safe_to_withdraw": assessment.is_safe_to_withdraw,
                "unique_sources": assessment.unique_sources,
                "warnings": assessment.warnings,
            }
        except Exception:
            # Fallback if analysis fails (e.g., node API unavailable)
            privacy_data = {
                "privacy_score": None,
                "risk_level": "UNKNOWN",
                "is_safe_to_withdraw": False,
                "unique_sources": None,
                "warnings": ["Anonymity analysis unavailable"],
            }

        return {
            "box_id": pool_box_id,
            "value_nanoerg": box["value"],
            "value_erg": box["value"] / NANOERG,
            "deposit_count": counter,
            "denomination": denom,
            **privacy_data,
        }

    @staticmethod
    def _decode_sigma_long(hex_str: str) -> int:
        """Decode a Sigma Long register value."""
        if not hex_str or len(hex_str) < 4:
            return 0
        # Skip 0x05 type byte, decode VLQ/ZigZag
        data = bytes.fromhex(hex_str[2:])
        n = 0
        shift = 0
        for b in data:
            n |= (b & 0x7F) << shift
            shift += 7
            if not (b & 0x80):
                break
        # ZigZag decode
        return (n >> 1) ^ -(n & 1)
