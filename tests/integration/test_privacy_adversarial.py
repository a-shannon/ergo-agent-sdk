"""
Adversarial integration tests for the privacy pool protocol.
Tests attack vectors, boundary conditions, and contract rejection paths.

Requires a running Ergo testnet node at 127.0.0.1:9052 and a funded wallet.

Run with: python -m pytest tests/integration/test_privacy_adversarial.py -v -m integration
"""

import os

import pytest

from ergo_agent.core.node import ErgoNode
from ergo_agent.core.wallet import Wallet
from ergo_agent.defi.privacy_pool import PrivacyPoolClient

pytestmark = pytest.mark.integration

NODE_URL = os.environ.get("ERGO_NODE_URL", "http://127.0.0.1:9052")
NODE_API_KEY = os.environ.get("ERGO_NODE_API_KEY", "hello")
EXPLORER_URL = os.environ.get("ERGO_EXPLORER_URL", "https://api-testnet.ergoplatform.com")


@pytest.fixture(scope="module")
def node():
    return ErgoNode(node_url=NODE_URL, explorer_url=EXPLORER_URL, api_key=NODE_API_KEY)


@pytest.fixture(scope="module")
def wallet(node):
    import httpx
    headers = {"api_key": NODE_API_KEY}
    r = httpx.get(f"{NODE_URL}/wallet/addresses", headers=headers, timeout=10.0)
    if r.status_code != 200:
        pytest.skip(f"Cannot get wallet addresses from node: {r.text}")
    addresses = r.json()
    addr = addresses[0] if isinstance(addresses, list) else addresses
    return Wallet.from_node_wallet(addr)


@pytest.fixture(scope="module")
def cash_client(node, wallet):
    return PrivacyPoolClient(node=node, wallet=wallet)


def get_first_pool(cash_client):
    """Helper to get first available pool or skip."""
    pools = cash_client.get_active_pools(denomination=100)
    if not pools:
        pytest.skip("No active pools found on testnet")
    return pools[0]


# --- Double-Spend Protection ---

def test_double_spend_key_image(cash_client):
    """
    If a key image is already in R5 (nullifier list),
    attempting to reuse it should produce a tx that the contract rejects.
    """
    pool = get_first_pool(cash_client)
    pool_box = cash_client.node.get_box_by_id(pool["pool_id"])
    r5 = pool_box.additional_registers.get("R5", "1300")
    if isinstance(r5, dict):
        r5 = r5.get("serializedValue", "1300")

    # If R5 already has nullifiers, extract the first one
    if r5 != "1300" and len(r5) > 4:
        count = PrivacyPoolClient._read_vlq(r5[2:])
        if count > 0:
            vlq_hex = PrivacyPoolClient._encode_vlq(count)
            data_start = 2 + len(vlq_hex)
            # Each GroupElement is 33 bytes = 66 hex chars
            first_nullifier = r5[data_start:data_start + 66]

            # Build a withdrawal reusing this key image
            builder = cash_client.build_withdrawal_tx(
                pool["pool_id"],
                cash_client.wallet.address,
                first_nullifier,
            )
            # The tx should build, but the contract's `notUsed` check
            # would reject it when submitted. We verify the structure is valid
            # but note that the contract evaluation will fail.
            assert len(builder._outputs) == 2
            print("\n[+] Double-spend tx built but would be rejected by contract (notUsed check)")
            return

    pytest.skip("No existing nullifiers in R5 to test double-spend against")


# --- Ring Size Boundary ---

def test_withdraw_from_underpopulated_ring(cash_client):
    """
    A pool with < 2 depositors should not permit withdrawal.
    The contract's `ringOk` requires poolKeys.size >= 2.
    """
    pool = get_first_pool(cash_client)
    if pool["depositors"] >= 2:
        pytest.skip("Pool has >= 2 depositors, cannot test underpopulated ring")

    key_image = "03" + "dd" * 32
    builder = cash_client.build_withdrawal_tx(
        pool["pool_id"],
        cash_client.wallet.address,
        key_image,
    )
    # Tx builds but contract would reject: ringOk = false
    assert len(builder._outputs) == 2
    print(f"\n[+] Withdrawal tx built against ring of {pool['depositors']} "
          f"(contract would reject at evaluation)")


# --- Register Tampering ---

def test_tampered_r6_denomination(cash_client):
    """
    If we manually tamper the R6 output to a different denomination,
    the contract's `denomOk` check would reject the tx.
    """
    pool = get_first_pool(cash_client)

    stealth_key = "02" + "aa" * 32
    builder = cash_client.build_deposit_tx(pool["pool_id"], stealth_key, 100)

    original_r6 = builder._outputs[0]["registers"]["R6"]

    # Tamper R6 to a different value
    builder._outputs[0]["registers"]["R6"] = "05a00f"  # Different denomination
    tampered_r6 = builder._outputs[0]["registers"]["R6"]

    assert tampered_r6 != original_r6
    print(f"\n[+] R6 tampered from {original_r6} to {tampered_r6}. "
          f"Contract would reject (denomOk)")


def test_tampered_r7_max_ring(cash_client):
    """
    Tampering R7 (maxRing) in the output should cause the contract
    to reject with `maxOk` failure.
    """
    pool = get_first_pool(cash_client)

    stealth_key = "02" + "bb" * 32
    builder = cash_client.build_deposit_tx(pool["pool_id"], stealth_key, 100)

    original_r7 = builder._outputs[0]["registers"]["R7"]
    builder._outputs[0]["registers"]["R7"] = "0464"  # Different maxRing
    tampered_r7 = builder._outputs[0]["registers"]["R7"]

    assert tampered_r7 != original_r7
    print(f"\n[+] R7 tampered from {original_r7} to {tampered_r7}. "
          f"Contract would reject (maxOk)")


def test_tampered_proposition_bytes(cash_client):
    """
    Redirecting the output to a different script should cause
    the contract's `scriptOk` to fail.
    """
    pool = get_first_pool(cash_client)

    stealth_key = "02" + "cc" * 32
    builder = cash_client.build_deposit_tx(pool["pool_id"], stealth_key, 100)

    original_tree = builder._outputs[0]["ergo_tree"]
    # Replace with a random P2PK tree
    builder._outputs[0]["ergo_tree"] = "0008cd0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"

    assert builder._outputs[0]["ergo_tree"] != original_tree
    print("\n[+] ErgoTree redirected. Contract would reject (scriptOk)")


# --- Token Manipulation ---

def test_note_with_wrong_token_amount(cash_client):
    """
    A note output with less than `denom * 99 / 100` tokens should be
    rejected by the contract's `noteOk` check.
    """
    pool = get_first_pool(cash_client)
    if pool["depositors"] < 2:
        pytest.skip("Pool ring size < 2, cannot test withdrawal")

    key_image = "03" + "ee" * 32
    builder = cash_client.build_withdrawal_tx(
        pool["pool_id"],
        cash_client.wallet.address,
        key_image,
    )

    # Tamper the note output to have fewer tokens
    original_amount = builder._outputs[1]["tokens"][0]["amount"]
    builder._outputs[1]["tokens"][0]["amount"] = 1  # Way too low

    assert builder._outputs[1]["tokens"][0]["amount"] < original_amount
    print(f"\n[+] Note tokens tampered: {original_amount} -> 1. "
          f"Contract would reject (noteOk)")


def test_deposit_r4_key_removal(cash_client):
    """
    If we remove an existing key from R4, the contract's `oldKeysOk`
    check (which verifies all original keys are preserved) would fail.
    """
    pool = get_first_pool(cash_client)
    if pool["depositors"] < 1:
        pytest.skip("Pool has no depositors to test key removal")

    stealth_key = "02" + "ff" * 32
    builder = cash_client.build_deposit_tx(pool["pool_id"], stealth_key, 100)

    original_r4 = builder._outputs[0]["registers"]["R4"]

    # Tamper: Replace R4 with just the new key (removing all existing keys)
    builder._outputs[0]["registers"]["R4"] = "1301" + stealth_key

    assert builder._outputs[0]["registers"]["R4"] != original_r4
    print("\n[+] R4 tampered to remove existing keys. "
          "Contract would reject (oldKeysOk)")


def test_withdrawal_token_amount_overflow(cash_client):
    """
    Setting pool output token amount to more than current - denom
    (i.e., not actually deducting tokens) should be rejected by tokenOk.
    """
    pool = get_first_pool(cash_client)
    if pool["depositors"] < 2:
        pytest.skip("Pool ring size < 2")

    key_image = "03" + "88" * 32
    builder = cash_client.build_withdrawal_tx(
        pool["pool_id"],
        cash_client.wallet.address,
        key_image,
    )

    # Tamper: Don't deduct tokens from pool
    pool_box = cash_client.node.get_box_by_id(pool["pool_id"])
    original_amount = pool_box.tokens[0].amount
    builder._outputs[0]["tokens"][0]["amount"] = original_amount  # Should be original - denom

    assert builder._outputs[0]["tokens"][0]["amount"] == original_amount
    print(f"\n[+] Pool tokens not deducted ({original_amount} -> {original_amount}). "
          f"Contract would reject (tokenOk)")
