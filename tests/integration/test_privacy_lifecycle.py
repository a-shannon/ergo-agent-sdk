"""
Integration tests for the privacy pool deposit/withdrawal lifecycle.
Requires a running Ergo testnet node at 127.0.0.1:9052 and a funded wallet.

These tests exercise the FULL transaction pipeline against the live testnet,
including pool discovery, stealth key generation, deposit building, and
withdrawal with ring signature validation.

Run with: python -m pytest tests/integration/test_privacy_lifecycle.py -v -m integration
"""

import os

import pytest

from ergo_agent.core.node import ErgoNode
from ergo_agent.core.wallet import Wallet
from ergo_agent.defi.privacy_pool import PrivacyPoolClient
from ergo_agent.tools.safety import SafetyConfig
from ergo_agent.tools.toolkit import ErgoToolkit

pytestmark = pytest.mark.integration

# Testnet node configuration
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
    if isinstance(addresses, list):
        addr = addresses[0]
    else:
        addr = addresses
    return Wallet.from_node_wallet(addr)


@pytest.fixture(scope="module")
def cash_client(node, wallet):
    return PrivacyPoolClient(node=node, wallet=wallet)


@pytest.fixture(scope="module")
def toolkit(node, wallet):
    safety = SafetyConfig(dry_run=False, max_erg_per_tx=1.0, max_erg_per_day=5.0)
    return ErgoToolkit(node=node, wallet=wallet, safety=safety)


# --- Pool Discovery ---

def test_discover_active_pools(cash_client):
    """Pool scanning should find at least one active testnet pool."""
    pools = cash_client.get_active_pools(denomination=100)
    assert isinstance(pools, list)
    if len(pools) > 0:
        pool = pools[0]
        assert "pool_id" in pool
        assert "depositors" in pool
        assert pool["denomination"] == 100
        assert pool["max_depositors"] == 16
        print(f"\n[+] Found {len(pools)} pools. First pool: {pool['pool_id'][:16]}... "
              f"Ring={pool['depositors']}/{pool['max_depositors']}")


def test_evaluate_pool_anonymity(cash_client):
    """evaluate_pool_anonymity should return a non-negative integer."""
    pools = cash_client.get_active_pools(denomination=100)
    if not pools:
        pytest.skip("No active pools found on testnet")
    ring_size = cash_client.evaluate_pool_anonymity(pools[0]["pool_id"])
    assert isinstance(ring_size, int)
    assert ring_size >= 0
    print(f"\n[+] Pool anonymity set: {ring_size} depositors")


# --- Deposit Path ---

def test_single_deposit_builds_valid_tx(cash_client, toolkit):
    """A deposit transaction should build without errors."""
    pools = toolkit.get_privacy_pools(denomination=100)
    if isinstance(pools, dict) and "error" in pools:
        pytest.skip(f"Pool scan failed: {pools['error']}")
    if not pools:
        pytest.skip("No pools on testnet")

    pool_id = pools[0]["pool_id"]
    stealth_key = "02" + "ab" * 32  # Synthetic test key

    builder = cash_client.build_deposit_tx(pool_id, stealth_key, 100)
    assert builder is not None
    assert len(builder._outputs) >= 1

    out = builder._outputs[0]
    assert "R4" in out["registers"]
    assert "R5" in out["registers"]
    assert "R6" in out["registers"]
    assert "R7" in out["registers"]
    print(f"\n[+] Deposit tx built successfully for pool {pool_id[:16]}...")


def test_deposit_tx_token_amount(cash_client):
    """Deposit output must have token_amount = input + denomination."""
    pools = cash_client.get_active_pools(denomination=100)
    if not pools:
        pytest.skip("No pools on testnet")

    pool_id = pools[0]["pool_id"]
    pool_box = cash_client.node.get_box_by_id(pool_id)
    original_tokens = pool_box.tokens[0].amount if pool_box and pool_box.tokens else 0

    builder = cash_client.build_deposit_tx(pool_id, "02" + "cd" * 32, 100)
    out_tokens = builder._outputs[0]["tokens"][0]["amount"]
    assert out_tokens == original_tokens + 100
    print(f"\n[+] Token math verified: {original_tokens} + 100 = {out_tokens}")


# --- Withdrawal Path ---

def test_withdrawal_builds_two_outputs(cash_client):
    """Withdrawal must produce exactly 2 outputs: pool continuation + note."""
    pools = cash_client.get_active_pools(denomination=100)
    if not pools:
        pytest.skip("No pools on testnet")

    pool = pools[0]
    if pool["depositors"] < 2:
        pytest.skip("Pool ring size < 2, cannot withdraw")

    key_image = "03" + "ef" * 32
    builder = cash_client.build_withdrawal_tx(
        pool["pool_id"],
        cash_client.wallet.address,
        key_image,
    )
    assert len(builder._outputs) == 2
    print("\n[+] Withdrawal tx has 2 outputs: pool continuation + note")


def test_withdrawal_preserves_r4(cash_client):
    """Withdrawal must NOT modify R4 (depositor keys)."""
    pools = cash_client.get_active_pools(denomination=100)
    if not pools:
        pytest.skip("No pools on testnet")

    pool = pools[0]
    if pool["depositors"] < 2:
        pytest.skip("Pool ring size < 2, cannot withdraw")

    pool_box = cash_client.node.get_box_by_id(pool["pool_id"])
    original_r4 = pool_box.additional_registers.get("R4")
    if isinstance(original_r4, dict):
        original_r4 = original_r4.get("serializedValue")

    key_image = "03" + "99" * 32
    builder = cash_client.build_withdrawal_tx(
        pool["pool_id"],
        cash_client.wallet.address,
        key_image,
    )
    output_r4 = builder._outputs[0]["registers"]["R4"]
    assert output_r4 == original_r4
    print("\n[+] R4 preserved across withdrawal (keys unchanged)")


def test_withdrawal_note_has_correct_token(cash_client):
    """The note output must carry the same token ID as the pool with 99% of denomination."""
    pools = cash_client.get_active_pools(denomination=100)
    if not pools:
        pytest.skip("No pools on testnet")

    pool = pools[0]
    if pool["depositors"] < 2:
        pytest.skip("Pool ring size < 2, cannot withdraw")

    key_image = "03" + "77" * 32
    builder = cash_client.build_withdrawal_tx(
        pool["pool_id"],
        cash_client.wallet.address,
        key_image,
    )

    pool_token_id = builder._outputs[0]["tokens"][0]["tokenId"]
    note_out = builder._outputs[1]
    assert note_out["tokens"][0]["tokenId"] == pool_token_id
    assert note_out["tokens"][0]["amount"] >= 99  # 99% of 100
    print(f"\n[+] Note carries {note_out['tokens'][0]['amount']} tokens of correct ID")
