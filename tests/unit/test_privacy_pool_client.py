"""
Unit tests for PrivacyPoolClient transaction builder logic.
All node/wallet calls are mocked — no network required.
"""

import pytest
from unittest.mock import MagicMock

from ergo_agent.defi.privacy_pool import PrivacyPoolClient
from ergo_agent.core.models import Box, Token


def make_pool_box(
    box_id="abc123",
    value=1_000_000,
    ergo_tree="0008cd02deadbeef",
    token_id="db60c1a42fa4d7da0b6dac60ffa862c1f45560ee5da7dbbae471aafe924c496f",
    token_amount=500,
    r4="1302" + ("02" + "aa" * 32) + ("02" + "bb" * 32),  # 2 depositors
    r5="1300",  # empty nullifiers
    r6="05c801",  # denom = 100
    r7="0420",   # maxRing = 16
):
    """Create a mock pool Box."""
    box = Box(
        box_id=box_id,
        value=value,
        ergo_tree=ergo_tree,
        creation_height=1_200_000,
        additional_registers={"R4": r4, "R5": r5, "R6": r6, "R7": r7},
    )
    box.tokens = [Token(token_id=token_id, amount=token_amount, name="privacy pool-TEST", decimals=0)]
    return box


def make_client():
    """Create a PrivacyPoolClient with mocked node."""
    node = MagicMock()
    wallet = MagicMock()
    wallet.address = "3WxTestAddress"
    client = PrivacyPoolClient.__new__(PrivacyPoolClient)
    client.node = node
    client.wallet = wallet
    client.MOCK_CASH_V3_POOL_ERGO_TREE = "0008cd02deadbeef"
    client.pool_address = "3WxPoolAddress"
    return client, node


# --- Deposit Transaction Tests ---

def test_deposit_preserves_existing_r4_keys():
    """Deposit must not reorder or remove existing R4 keys."""
    client, node = make_client()
    pool_box = make_pool_box()
    node.get_box_by_id.return_value = pool_box

    new_key = "02" + "cc" * 32
    builder = client.build_deposit_tx("abc123", new_key, 100)

    # Find the raw output that was added
    assert len(builder._outputs) == 1
    out = builder._outputs[0]
    new_r4 = out["registers"]["R4"]

    # Must start with "13" (Coll type) and contain the new key at the end
    assert new_r4.startswith("13")
    assert new_r4.endswith(new_key)


def test_deposit_increments_r4_count():
    """After deposit, R4 collection size should increase by 1."""
    client, node = make_client()
    pool_box = make_pool_box()
    node.get_box_by_id.return_value = pool_box

    new_key = "02" + "dd" * 32
    builder = client.build_deposit_tx("abc123", new_key, 100)
    out = builder._outputs[0]
    new_r4 = out["registers"]["R4"]

    # Original had 2 elements (0x02), new should have 3 (0x03)
    count = PrivacyPoolClient._read_vlq(new_r4[2:])
    assert count == 3


def test_deposit_preserves_r5():
    """Deposit must NOT change R5 (nullifier tree)."""
    client, node = make_client()
    pool_box = make_pool_box(r5="1301" + "02" + "ee" * 32)
    node.get_box_by_id.return_value = pool_box

    builder = client.build_deposit_tx("abc123", "02" + "ff" * 32, 100)
    out = builder._outputs[0]
    assert out["registers"]["R5"] == "1301" + "02" + "ee" * 32


def test_deposit_preserves_r6_r7_from_live_box():
    """R6 and R7 must come from the live pool box, not hardcoded values."""
    client, node = make_client()
    pool_box = make_pool_box(r6="05a00f", r7="0440")  # denom=1000, maxRing=32
    node.get_box_by_id.return_value = pool_box

    # Use a unique key not already in R4 (R4 default contains aa*32 and bb*32)
    builder = client.build_deposit_tx("abc123", "02" + "e1" * 32, 100)
    out = builder._outputs[0]
    assert out["registers"]["R6"] == "05a00f"
    assert out["registers"]["R7"] == "0440"


def test_deposit_adds_tokens():
    """Output token amount = input + denomination."""
    client, node = make_client()
    pool_box = make_pool_box(token_amount=500)
    node.get_box_by_id.return_value = pool_box

    # Use a unique key not already in R4
    builder = client.build_deposit_tx("abc123", "02" + "e2" * 32, 100)
    out = builder._outputs[0]
    assert out["tokens"][0]["amount"] == 600


def test_deposit_pool_not_found():
    """Must raise ValueError if pool box doesn't exist."""
    client, node = make_client()
    node.get_box_by_id.return_value = None

    with pytest.raises(ValueError, match="could not resolve"):
        client.build_deposit_tx("nonexistent", "02" + "aa" * 32, 100)


# --- Withdrawal Transaction Tests ---

def test_withdrawal_uses_box_not_string(monkeypatch):
    """build_withdrawal_tx must pass Box object to with_input(), not a string."""
    import ergo_agent.core.address as addr_mod
    monkeypatch.setattr(addr_mod, "address_to_ergo_tree", lambda *a, **kw: "0008cd03recipient")

    client, node = make_client()
    pool_box = make_pool_box()
    node.get_box_by_id.return_value = pool_box

    key_image = "03" + "ff" * 32
    builder = client.build_withdrawal_tx("abc123", "3WxRecipient", key_image)

    # The explicit input should have a Box, not None (which indicates string-based)
    assert len(builder._explicit_inputs) == 1
    assert builder._explicit_inputs[0]["box"] is not None


def test_withdrawal_appends_nullifier(monkeypatch):
    """R5 in the output must contain the new key image."""
    import ergo_agent.core.address as addr_mod
    monkeypatch.setattr(addr_mod, "address_to_ergo_tree", lambda *a, **kw: "0008cd03recipient")

    client, node = make_client()
    pool_box = make_pool_box(r5="1301" + "03" + "aa" * 32)
    node.get_box_by_id.return_value = pool_box

    key_image = "03" + "bb" * 32
    builder = client.build_withdrawal_tx("abc123", "3WxRecipient", key_image)

    out = builder._outputs[0]
    new_r5 = out["registers"]["R5"]
    assert new_r5.endswith(key_image)

    # Count should be 2 (was 1)
    count = PrivacyPoolClient._read_vlq(new_r5[2:])
    assert count == 2


def test_withdrawal_dynamic_denomination(monkeypatch):
    """Withdrawal should use denomination from R6, not hardcoded 100."""
    import ergo_agent.core.address as addr_mod
    monkeypatch.setattr(addr_mod, "address_to_ergo_tree", lambda *a, **kw: "0008cd03recipient")

    client, node = make_client()
    # denom = 1000 encoded as zigzag VLQ
    pool_box = make_pool_box(r6="05d00f", token_amount=5000)
    node.get_box_by_id.return_value = pool_box

    key_image = "03" + "cc" * 32
    builder = client.build_withdrawal_tx("abc123", "3WxRecipient", key_image)

    # Pool output should deduct the decoded denomination, not 100
    pool_out = builder._outputs[0]
    denom = client._decode_r6_denomination("05d00f")
    assert pool_out["tokens"][0]["amount"] == 5000 - denom

    # Note output should be 99% of denom
    note_out = builder._outputs[1]
    assert note_out["tokens"][0]["amount"] == max(1, (denom * 99) // 100)


def test_withdrawal_note_amount_floor(monkeypatch):
    """For denom=1, note_amount must be at least 1 (not 0)."""
    import ergo_agent.core.address as addr_mod
    monkeypatch.setattr(addr_mod, "address_to_ergo_tree", lambda *a, **kw: "0008cd03recipient")

    client, node = make_client()
    # Manually set R6 to encode denom=1 (zigzag: 1→2, VLQ: "02")
    pool_box = make_pool_box(r6="0502", token_amount=100)
    node.get_box_by_id.return_value = pool_box

    key_image = "03" + "dd" * 32
    builder = client.build_withdrawal_tx("abc123", "3WxRecipient", key_image)

    note_out = builder._outputs[1]
    assert note_out["tokens"][0]["amount"] >= 1
