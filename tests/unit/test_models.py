"""
Unit tests for core data models.
"""

import pytest

from ergo_agent.core.models import Balance, Box, SwapQuote, Token


def test_token_amount_display_no_decimals():
    t = Token(token_id="abc", amount=1000, decimals=0)
    assert t.amount_display == 1000


def test_token_amount_display_with_decimals():
    t = Token(token_id="abc", amount=100, decimals=2)  # like SigUSD
    assert t.amount_display == 1.0


def test_box_value_erg():
    box = Box(
        box_id="abc123",
        value=2_000_000_000,  # 2 ERG
        ergo_tree="deadbeef",
        creation_height=1234,
    )
    assert box.value_erg == pytest.approx(2.0)


def test_balance_summary():
    balance = Balance(
        address="9fXWbP...",
        erg=10.5,
        erg_nanoerg=10_500_000_000,
        tokens=[
            Token(token_id="abc", amount=100, name="SigUSD", decimals=2)
        ],
    )
    summary = balance.to_agent_summary()
    assert "ERG: 10.5000" in summary
    assert "SigUSD: 1.0" in summary


def test_swap_quote_price():
    quote = SwapQuote(
        pool_id="pool1",
        token_in_id="ERG",
        token_in_amount=1_000_000_000,  # 1 ERG
        token_out_id="SigUSD",
        token_out_amount=87,  # 0.87 SigUSD in cents
        price_impact_pct=0.1,
        fee_pct=0.3,
    )
    assert quote.price == pytest.approx(87 / 1_000_000_000)
