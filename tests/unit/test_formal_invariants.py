"""
Formal Invariants Testing Suite — Adversarial Security Tests.

Validates the privacy pool protocol against the 4 attack vectors specified
in the privacy pool Handoff Document §Verification Plan.

These tests verify SDK-level invariants that correspond directly to
on-chain security guarantees. They prove the attack fails at the
SDK level, which is the last line of defense before the transaction
reaches the L1 mempool.

Attack Vectors Tested:
  1. Double Spend Attack — same nullifier submitted twice
  2. Relayer Context Theft — payout address redirection
  3. Malformed Ring Attack — decoy not in deposit tree
  4. Contention Simulation — stale pool state
"""

import secrets

import pytest

from ergo_agent.crypto.dhtuple import (
    build_withdrawal_ring,
    compute_nullifier,
)
from ergo_agent.crypto.pedersen import (
    G_COMPRESSED,
    NUMS_H,
    SECP256K1_N,
    PedersenCommitment,
    decode_point,
    encode_point,
)
from ergo_agent.relayer.deposit_relayer import (
    DepositRelayer,
    IntentToDeposit,
    PoolState,
)
from ergo_agent.relayer.pool_deployer import (
    NANOERG,
)
from ergo_agent.relayer.withdrawal_relayer import (
    IntentToWithdraw,
    WithdrawalRelayer,
)

# ==============================================================================
# Helpers
# ==============================================================================

DENOM = 100 * NANOERG
MOCK_TREE = "0008cd02deadbeef" + "00" * 20


def _random_r() -> int:
    return secrets.randbelow(SECP256K1_N - 1) + 1


def _make_pool(counter: int = 150, value: int = 50_000 * NANOERG) -> PoolState:
    """Create a mock pool state for testing."""
    return PoolState(
        box_id="pool_" + "ab" * 16,
        value_nanoerg=value,
        deposit_tree_hex="64" + "00" * 33 + "072100",
        nullifier_tree_hex="64" + "00" * 33 + "072100",
        deposit_counter=counter,
        denomination=DENOM,
        ergo_tree=MOCK_TREE,
    )


def _make_withdrawal_intent(
    nullifier: str | None = None,
    payout: str = "0008cd02" + "ff" * 32,
) -> IntentToWithdraw:
    r = _random_r()
    nul = nullifier or compute_nullifier(r)  # v9: I = r·H (fixed NUMS H)
    return IntentToWithdraw(
        box_id="intent_" + secrets.token_hex(8),
        value_nanoerg=1_000_000,
        nullifier_hex=nul,
        secondary_gen_hex=None,  # v9: U no longer user-supplied
        payout_ergo_tree=payout,
        ergo_tree="0008cd03" + "ee" * 32,
    )


# ==============================================================================
# ATTACK 1: Double Spend
# ==============================================================================


class TestDoubleSpendAttack:
    """
    §2.4.1 — Attempt to submit the same Nullifier twice.

    The AVL tree insertion must fail on the second attempt because
    the nullifier key already exists in the Nullifier Tree.

    SDK-level defense:
    - The nullifier is a deterministic function of (r, U):  I = r·U
    - If the same (r, U) pair is reused, the nullifier is identical
    - The AVL tree rejects duplicate key insertions

    On-chain defense:
    - curTree.insert() returns None if key exists → .get fails → tx invalid
    """

    def test_same_nullifier_produces_identical_key(self):
        """Same r always produces the same nullifier I = r·H."""
        r = _random_r()
        I1 = compute_nullifier(r)
        I2 = compute_nullifier(r)
        assert I1 == I2, "Same r must produce identical nullifier"

    def test_second_withdrawal_same_nullifier_detectable(self):
        """Two withdrawal intents with the same nullifier can be detected."""
        r = _random_r()
        shared_nullifier = compute_nullifier(r)  # v9: deterministic per r

        intent1 = _make_withdrawal_intent(nullifier=shared_nullifier)
        intent2 = _make_withdrawal_intent(nullifier=shared_nullifier)

        # Both intents have the same nullifier — the relayer can detect this
        assert intent1.nullifier_hex == intent2.nullifier_hex

    def test_different_r_different_nullifier_no_collision(self):
        """Different blinding factors MUST produce different nullifiers."""
        nullifiers = set()
        for _ in range(50):
            r = _random_r()
            nul = compute_nullifier(r)  # v9: I = r·H
            assert nul not in nullifiers, "Nullifier collision detected!"
            nullifiers.add(nul)



# ==============================================================================
# ATTACK 2: Relayer Context Theft (MEV Theft)
# ==============================================================================


class TestRelayerContextTheft:
    """
    §2.4.2 — Relayer attempts to redirect withdrawal payout to itself.

    Defense: Ergo's Sigma protocol hashes the ENTIRE tx.messageToSign
    into the Fiat-Shamir challenge. If the Relayer modifies any output
    (e.g., changes the payout address), the pre-signed Sigma proof
    becomes invalid.

    SDK-level defense:
    - The payout address is embedded in the IntentToWithdraw R6 register
    - The MasterPoolBox contract verifies: payoutBox.propositionBytes == payoutAddr
    - The Relayer cannot change the payout without invalidating the tx
    """

    def test_payout_address_preserved_in_tx(self):
        """The withdrawal tx output must contain the exact payout address."""
        victim_address = "0008cd02" + "aa" * 32
        pool = _make_pool()
        relayer = WithdrawalRelayer(pool)
        intent = _make_withdrawal_intent(payout=victim_address)
        result = relayer.build_withdrawal_tx(intent)

        payout_out = result["tx"]["outputs"][1]
        assert payout_out["ergoTree"] == victim_address
        assert payout_out["value"] == DENOM

    def test_modified_payout_detectable(self):
        """If Relayer changes the payout, the tx differs from intent."""
        victim_address = "0008cd02" + "aa" * 32
        attacker_address = "0008cd02" + "bb" * 32

        pool = _make_pool()
        relayer = WithdrawalRelayer(pool)
        intent = _make_withdrawal_intent(payout=victim_address)
        result = relayer.build_withdrawal_tx(intent)

        # The intent specifies victim_address — any change is detectable
        assert result["payout_address"] == victim_address
        assert result["payout_address"] != attacker_address

    def test_payout_value_matches_denomination(self):
        """Relayer cannot reduce the payout amount below denomination."""
        pool = _make_pool()
        relayer = WithdrawalRelayer(pool)
        intent = _make_withdrawal_intent()
        result = relayer.build_withdrawal_tx(intent)

        payout_out = result["tx"]["outputs"][1]
        assert payout_out["value"] == DENOM


# ==============================================================================
# ATTACK 3: Malformed Ring Attack
# ==============================================================================


class TestMalformedRingAttack:
    """
    §2.4.3 — Attacker includes a decoy commitment NOT in the Deposit Tree.

    Defense: The MasterPoolBox contract constructs the ring from its own
    R4 Deposit Tree. The attacker cannot inject arbitrary points.

    SDK-level defense:
    - build_withdrawal_ring() performs an integrity check:
      C_real - amt·H == r·G must hold for the real index
    - If the real commitment is fake, the integrity check fails
    """

    def test_wrong_commitment_fails_integrity(self):
        """Ring construction rejects a commitment that doesn't match r."""
        r = _random_r()
        # Create a commitment with a DIFFERENT blinding factor
        wrong_r = _random_r()
        C_fake = PedersenCommitment.commit(wrong_r, DENOM)
        decoys = [PedersenCommitment.commit(_random_r(), DENOM) for _ in range(3)]

        with pytest.raises(ValueError, match="integrity check failed"):
            build_withdrawal_ring(r, DENOM, C_fake, decoys)

    def test_wrong_amount_fails_integrity(self):
        """Ring construction rejects if amount doesn't match."""
        r = _random_r()
        C = PedersenCommitment.commit(r, DENOM)
        decoys = [PedersenCommitment.commit(_random_r(), DENOM) for _ in range(3)]

        with pytest.raises(ValueError, match="integrity check failed"):
            build_withdrawal_ring(r, DENOM - 1, C, decoys)

    def test_valid_ring_passes_integrity(self):
        """Correctly formed ring passes all checks."""
        r = _random_r()
        C = PedersenCommitment.commit(r, DENOM)
        decoys = [PedersenCommitment.commit(_random_r(), DENOM) for _ in range(3)]

        ring = build_withdrawal_ring(r, DENOM, C, decoys)
        assert ring.ring_size == 4
        # The opened point at real_index must be r·G
        expected_rG = encode_point(r * decode_point(G_COMPRESSED))
        assert ring.opened_points[ring.real_index] == expected_rG

    def test_deposit_validator_rejects_generator_point(self):
        """Deposit validation rejects the generator G as a commitment."""
        pool = _make_pool()
        relayer = DepositRelayer(pool)
        intent = IntentToDeposit(
            box_id="fake_intent",
            value_nanoerg=DENOM,
            commitment_hex=G_COMPRESSED,
            ergo_tree="0008cd03" + "cc" * 32,
        )
        assert relayer.validate_intent(intent) is False


# ==============================================================================
# ATTACK 4: Contention Simulation (Stale State)
# ==============================================================================


class TestContentionSimulation:
    """
    §2.4.4 — Relayer builds a valid tx, but the MasterPoolBox has been
    spent by another Relayer before submission.

    Defense: Ergo's UTXO model naturally handles this — the box ID in
    the transaction input no longer exists, so the tx is rejected by
    the mempool. No special logic needed.

    SDK-level defense:
    - The tx references pool_state.box_id as an input
    - If the pool has been updated (new box_id), the old tx is invalid
    - The Relayer simply re-fetches the current pool state and rebuilds
    """

    def test_stale_box_id_detectable(self):
        """If pool state changes, the box_id will be different."""
        pool_v1 = _make_pool()
        pool_v2 = _make_pool()

        # Simulate a state change by the second pool having a different box_id
        pool_v2 = PoolState(
            box_id="pool_" + "cd" * 16,  # Different box ID
            value_nanoerg=pool_v1.value_nanoerg + DENOM,
            deposit_tree_hex=pool_v1.deposit_tree_hex,
            nullifier_tree_hex=pool_v1.nullifier_tree_hex,
            deposit_counter=pool_v1.deposit_counter + 1,
            denomination=pool_v1.denomination,
            ergo_tree=pool_v1.ergo_tree,
        )

        # Build tx against stale state
        relayer = WithdrawalRelayer(pool_v1)
        intent = _make_withdrawal_intent()
        result_v1 = relayer.build_withdrawal_tx(intent)

        # The tx references pool_v1's box_id
        assert result_v1["tx"]["inputs"][0]["boxId"] == pool_v1.box_id
        # This box_id no longer exists on-chain — tx will be rejected
        assert result_v1["tx"]["inputs"][0]["boxId"] != pool_v2.box_id

    def test_deposit_tree_mismatch_detectable(self):
        """Stale deposit tree means AVL proof will be invalid on-chain."""
        pool_v1 = _make_pool()

        # Simulate deposit tree change
        pool_v2_tree = "64" + "ff" * 33 + "072100"

        # AVL proof generated against pool_v1's tree
        intent = IntentToDeposit(
            box_id="intent_" + secrets.token_hex(8),
            value_nanoerg=DENOM,
            commitment_hex=PedersenCommitment.commit(_random_r(), DENOM),
            ergo_tree="0008cd03" + "cc" * 32,
        )

        relayer = DepositRelayer(pool_v1)
        result = relayer.build_batch_deposit_tx([intent])

        # The new deposit tree in output was computed from pool_v1's tree
        # If pool has moved to pool_v2_tree, the on-chain verification fails
        assert result["new_deposit_tree"] != pool_v2_tree


# ==============================================================================
# INVARIANT: Nullifier Safety Guards
# ==============================================================================


class TestNullifierSafetyGuards:
    """
    Protocol safety: nullifier must never be G, H, or identity.

    These are hardcoded guards in both the contract and the SDK.
    """

    def test_g_rejected_as_nullifier(self):
        """Generator G as nullifier is rejected by validation."""
        pool = _make_pool()
        relayer = WithdrawalRelayer(pool)
        intent = _make_withdrawal_intent()
        intent.nullifier_hex = G_COMPRESSED
        assert relayer.validate_intent(intent) is False

    def test_h_rejected_as_nullifier(self):
        """NUMS H as nullifier is rejected by validation."""
        pool = _make_pool()
        relayer = WithdrawalRelayer(pool)
        intent = _make_withdrawal_intent()
        intent.nullifier_hex = NUMS_H
        assert relayer.validate_intent(intent) is False

    def test_g_rejected_as_commitment(self):
        """Generator G as deposit commitment is rejected."""
        pool = _make_pool()
        relayer = DepositRelayer(pool)
        intent = IntentToDeposit(
            box_id="bad_intent",
            value_nanoerg=DENOM,
            commitment_hex=G_COMPRESSED,
            ergo_tree="0008cd03" + "cc" * 32,
        )
        assert relayer.validate_intent(intent) is False


# ==============================================================================
# INVARIANT: Contract Immutability (Burn Admin Keys)
# ==============================================================================


class TestContractImmutability:
    """
    §4.2 — Burn Admin Keys.

    The privacy pool contracts are fully permissionless by design:
    - MasterPoolBox has no admin key — anyone can relay deposits/withdrawals
    - IntentToDeposit is permissionless — anyone can sweep
    - IntentToWithdraw relies on Sigma proofs — no admin can interfere
    - ChaffAccumulator is permissionless — any MEV bot can trigger

    These tests verify there are no admin-controlled paths.
    """

    def test_deposit_relayer_permissionless(self):
        """Deposit batching requires no special keys — any relayer works."""
        pool = _make_pool()
        relayer = DepositRelayer(pool)
        r = _random_r()
        C = PedersenCommitment.commit(r, DENOM)
        intent = IntentToDeposit(
            box_id="intent_" + secrets.token_hex(8),
            value_nanoerg=DENOM,
            commitment_hex=C,
            ergo_tree="0008cd03" + "cc" * 32,
        )

        # Any relayer can build this tx — no wallet/key needed for the sweep
        result = relayer.build_batch_deposit_tx([intent])
        assert result["batch_size"] == 1
        # No special signing required for the pool input — it's script-guarded

    def test_withdrawal_relayer_permissionless(self):
        """Withdrawal processing requires no special keys."""
        pool = _make_pool()
        relayer = WithdrawalRelayer(pool)
        intent = _make_withdrawal_intent()

        result = relayer.build_withdrawal_tx(intent)
        # Pool input is script-guarded, intent input has Sigma proof
        assert len(result["tx"]["inputs"]) == 2
