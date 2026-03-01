"""
Unit tests for ergo_agent.relayer — Deposit and Withdrawal Relayer logic.

Tests the transaction building, validation, and state management without
requiring a live Ergo node or the ergo_avltree Rust extension.
"""

import secrets

import pytest

from ergo_agent.crypto.dhtuple import (
    compute_nullifier,
)
from ergo_agent.crypto.pedersen import (
    G_COMPRESSED,
    NUMS_H,
    SECP256K1_N,
    PedersenCommitment,
)
from ergo_agent.relayer.deposit_relayer import (
    MAX_BATCH_SIZE,
    MINER_FEE,
    DepositRelayer,
    IntentToDeposit,
    PoolState,
)
from ergo_agent.relayer.withdrawal_relayer import (
    IntentToWithdraw,
    WithdrawalRelayer,
)

# ==============================================================================
# Helpers
# ==============================================================================


DENOM = 100_000_000_000  # 100 ERG in nanoERG
MOCK_ERGO_TREE = "0008cd02deadbeef" + "00" * 20


def _random_blinding() -> int:
    return secrets.randbelow(SECP256K1_N - 1) + 1


def _make_pool_state(
    value: int = 10_000_000_000_000,
    counter: int = 50,
    denom: int = DENOM,
) -> PoolState:
    return PoolState(
        box_id="pool_" + "ab" * 16,
        value_nanoerg=value,
        deposit_tree_hex="64" + "00" * 33 + "072100",
        nullifier_tree_hex="64" + "00" * 33 + "072100",
        deposit_counter=counter,
        denomination=denom,
        ergo_tree=MOCK_ERGO_TREE,
    )


def _make_intent_deposit(
    denom: int = DENOM,
    commitment_hex: str | None = None,
) -> IntentToDeposit:
    r = _random_blinding()
    C = commitment_hex or PedersenCommitment.commit(r, denom)
    return IntentToDeposit(
        box_id="intent_" + secrets.token_hex(8),
        value_nanoerg=denom,
        commitment_hex=C,
        ergo_tree="0008cd03" + "cc" * 32,
    )


def _make_intent_withdraw(
    payout_tree: str = "0008cd02" + "dd" * 32,
) -> IntentToWithdraw:
    r = _random_blinding()
    nul = compute_nullifier(r)  # v9: I = r·H
    return IntentToWithdraw(
        box_id="withdraw_" + secrets.token_hex(8),
        value_nanoerg=1_000_000,
        nullifier_hex=nul,
        secondary_gen_hex=None,  # v9: U=H hardcoded in contract
        payout_ergo_tree=payout_tree,
        ergo_tree="0008cd03" + "ee" * 32,
    )


# ==============================================================================
# DepositRelayer tests
# ==============================================================================


class TestDepositRelayerValidation:
    """Tests for IntentToDeposit validation."""

    def test_valid_intent(self):
        pool = _make_pool_state()
        relayer = DepositRelayer(pool)
        intent = _make_intent_deposit()
        assert relayer.validate_intent(intent) is True

    def test_reject_insufficient_value(self):
        pool = _make_pool_state()
        relayer = DepositRelayer(pool)
        intent = _make_intent_deposit()
        intent.value_nanoerg = DENOM - 1  # Too little
        assert relayer.validate_intent(intent) is False

    def test_reject_generator_commitment(self):
        pool = _make_pool_state()
        relayer = DepositRelayer(pool)
        intent = _make_intent_deposit(commitment_hex=G_COMPRESSED)
        assert relayer.validate_intent(intent) is False

    def test_reject_invalid_hex(self):
        pool = _make_pool_state()
        relayer = DepositRelayer(pool)
        intent = _make_intent_deposit(commitment_hex="not_valid_hex")
        assert relayer.validate_intent(intent) is False


class TestDepositRelayerBatch:
    """Tests for batch deposit transaction building."""

    def test_single_deposit(self):
        pool = _make_pool_state()
        relayer = DepositRelayer(pool)
        intent = _make_intent_deposit()
        result = relayer.build_batch_deposit_tx([intent])

        assert result["batch_size"] == 1
        tx = result["tx"]
        # 2 inputs: pool + 1 intent
        assert len(tx["inputs"]) == 2
        # 2 outputs: pool' + fee
        assert len(tx["outputs"]) == 2
        # Pool output value increased by denomination
        assert tx["outputs"][0]["value"] == pool.value_nanoerg + DENOM

    def test_multi_deposit(self):
        pool = _make_pool_state()
        relayer = DepositRelayer(pool)
        intents = [_make_intent_deposit() for _ in range(5)]
        result = relayer.build_batch_deposit_tx(intents)

        assert result["batch_size"] == 5
        tx = result["tx"]
        assert len(tx["inputs"]) == 6  # pool + 5 intents
        assert tx["outputs"][0]["value"] == pool.value_nanoerg + 5 * DENOM
        assert len(result["commitments"]) == 5

    def test_counter_increment(self):
        pool = _make_pool_state(counter=42)
        relayer = DepositRelayer(pool)
        intents = [_make_intent_deposit() for _ in range(3)]
        result = relayer.build_batch_deposit_tx(intents)

        # R6 should encode counter = 42 + 3 = 45
        r6 = result["tx"]["outputs"][0]["additionalRegisters"]["R6"]
        assert r6 == DepositRelayer._sigma_long(45)

    def test_nullifier_tree_unchanged(self):
        pool = _make_pool_state()
        relayer = DepositRelayer(pool)
        intent = _make_intent_deposit()
        result = relayer.build_batch_deposit_tx([intent])

        # R5 should be exactly the same as input
        r5 = result["tx"]["outputs"][0]["additionalRegisters"]["R5"]
        assert r5 == pool.nullifier_tree_hex

    def test_reject_empty(self):
        pool = _make_pool_state()
        relayer = DepositRelayer(pool)
        with pytest.raises(ValueError, match="No intent"):
            relayer.build_batch_deposit_tx([])

    def test_reject_over_max_batch(self):
        pool = _make_pool_state()
        relayer = DepositRelayer(pool)
        intents = [_make_intent_deposit() for _ in range(MAX_BATCH_SIZE + 1)]
        with pytest.raises(ValueError, match="Too many"):
            relayer.build_batch_deposit_tx(intents)

    def test_reject_invalid_intent_in_batch(self):
        pool = _make_pool_state()
        relayer = DepositRelayer(pool)
        good = _make_intent_deposit()
        bad = _make_intent_deposit(commitment_hex="02" + "00" * 32)
        bad.commitment_hex = "invalid"
        with pytest.raises(ValueError, match="failed validation"):
            relayer.build_batch_deposit_tx([good, bad])


# ==============================================================================
# WithdrawalRelayer tests
# ==============================================================================


class TestWithdrawalRelayerValidation:
    """Tests for IntentToWithdraw validation."""

    def test_valid_intent(self):
        pool = _make_pool_state()
        relayer = WithdrawalRelayer(pool)
        intent = _make_intent_withdraw()
        assert relayer.validate_intent(intent) is True

    def test_reject_generator_nullifier(self):
        pool = _make_pool_state()
        relayer = WithdrawalRelayer(pool)
        intent = _make_intent_withdraw()
        intent.nullifier_hex = G_COMPRESSED
        assert relayer.validate_intent(intent) is False

    def test_reject_h_nullifier(self):
        pool = _make_pool_state()
        relayer = WithdrawalRelayer(pool)
        intent = _make_intent_withdraw()
        intent.nullifier_hex = NUMS_H
        assert relayer.validate_intent(intent) is False

    def test_reject_empty_payout(self):
        pool = _make_pool_state()
        relayer = WithdrawalRelayer(pool)
        intent = _make_intent_withdraw(payout_tree="")
        assert relayer.validate_intent(intent) is False

    def test_reject_insufficient_pool_balance(self):
        pool = _make_pool_state(value=DENOM - 1)  # Not enough ERG
        relayer = WithdrawalRelayer(pool)
        intent = _make_intent_withdraw()
        assert relayer.validate_intent(intent) is False


class TestWithdrawalRelayerTx:
    """Tests for withdrawal transaction building."""

    def test_single_withdrawal(self):
        pool = _make_pool_state()
        relayer = WithdrawalRelayer(pool)
        intent = _make_intent_withdraw()
        result = relayer.build_withdrawal_tx(intent)

        tx = result["tx"]
        # 2 inputs: pool + intent
        assert len(tx["inputs"]) == 2
        # 3 outputs: pool' + payout + fee
        assert len(tx["outputs"]) == 3

    def test_pool_value_decreased(self):
        pool = _make_pool_state()
        relayer = WithdrawalRelayer(pool)
        intent = _make_intent_withdraw()
        result = relayer.build_withdrawal_tx(intent)

        pool_out = result["tx"]["outputs"][0]
        assert pool_out["value"] == pool.value_nanoerg - DENOM

    def test_payout_correct(self):
        payout_tree = "0008cd02" + "ff" * 32
        pool = _make_pool_state()
        relayer = WithdrawalRelayer(pool)
        intent = _make_intent_withdraw(payout_tree=payout_tree)
        result = relayer.build_withdrawal_tx(intent)

        payout_out = result["tx"]["outputs"][1]
        assert payout_out["value"] == DENOM
        assert payout_out["ergoTree"] == payout_tree

    def test_counter_unchanged(self):
        pool = _make_pool_state(counter=99)
        relayer = WithdrawalRelayer(pool)
        intent = _make_intent_withdraw()
        result = relayer.build_withdrawal_tx(intent)

        r6 = result["tx"]["outputs"][0]["additionalRegisters"]["R6"]
        assert r6 == WithdrawalRelayer._sigma_long(99)

    def test_deposit_tree_unchanged(self):
        pool = _make_pool_state()
        relayer = WithdrawalRelayer(pool)
        intent = _make_intent_withdraw()
        result = relayer.build_withdrawal_tx(intent)

        r4 = result["tx"]["outputs"][0]["additionalRegisters"]["R4"]
        assert r4 == pool.deposit_tree_hex

    def test_fee_output(self):
        pool = _make_pool_state()
        relayer = WithdrawalRelayer(pool)
        intent = _make_intent_withdraw()
        result = relayer.build_withdrawal_tx(intent)

        fee_out = result["tx"]["outputs"][2]
        assert fee_out["value"] == MINER_FEE

    def test_reject_invalid_intent(self):
        pool = _make_pool_state()
        relayer = WithdrawalRelayer(pool)
        intent = _make_intent_withdraw()
        intent.nullifier_hex = "invalid"
        with pytest.raises(ValueError, match="failed validation"):
            relayer.build_withdrawal_tx(intent)


# ==============================================================================
# Sigma serialization tests
# ==============================================================================


class TestSigmaSerialization:
    """Tests for internal Sigma encoding helpers."""

    def test_sigma_long_zero(self):
        assert DepositRelayer._sigma_long(0) == "0500"

    def test_sigma_long_100(self):
        # 100 zigzag = 200 = 0xC8 → VLQ = C801
        assert DepositRelayer._sigma_long(100) == "05c801"

    def test_sigma_long_roundtrip_consistency(self):
        # Both relayers should produce the same encoding
        assert DepositRelayer._sigma_long(42) == WithdrawalRelayer._sigma_long(42)
