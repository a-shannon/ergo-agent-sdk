"""Anthropic tool-use definitions for ErgoToolkit."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ergo_agent.tools.toolkit import ErgoToolkit


def build_anthropic_tools(toolkit: ErgoToolkit) -> list[dict[str, Any]]:
    """Return a list of Anthropic tool-use definitions."""
    return [
        {
            "name": "get_wallet_balance",
            "description": "Get the current ERG and token balance of the agent's Ergo wallet.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "get_erg_price",
            "description": (
                "Get the current ERG/USD price from the Ergo Oracle Pool v2 (on-chain). "
                "Returns the price in USD per 1 ERG."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "get_swap_quote",
            "description": (
                "Get a swap quote from Spectrum DEX without executing it. "
                "Check expected output and price impact before swapping."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "token_in": {"type": "string", "description": "Input token (e.g. 'ERG', 'SigUSD')"},
                    "token_out": {"type": "string", "description": "Output token (e.g. 'SigUSD', 'ERG')"},
                    "amount_erg": {"type": "number", "description": "ERG amount (if token_in is 'ERG')"},
                    "amount_token": {"type": "integer", "description": "Raw token amount (if token_in is a token)"},
                },
                "required": ["token_in", "token_out"],
            },
        },
        {
            "name": "send_erg",
            "description": "Send ERG to an Ergo address. Subject to safety limits.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Destination Ergo address"},
                    "amount_erg": {"type": "number", "description": "Amount in ERG"},
                },
                "required": ["to", "amount_erg"],
            },
        },
        {
            "name": "swap_erg_for_token",
            "description": "Swap ERG for a token on Spectrum DEX. Check quote first.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "token_out": {"type": "string", "description": "Token to receive"},
                    "amount_erg": {"type": "number", "description": "ERG to spend"},
                    "max_slippage_pct": {"type": "number", "description": "Max price impact % (default 1.0)"},
                },
                "required": ["token_out", "amount_erg"],
            },
        },
        {
            "name": "get_mempool_status",
            "description": "Check pending (unconfirmed) transactions from this wallet.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "get_safety_status",
            "description": "Get current safety limits and remaining daily budget.",
            "input_schema": {"type": "object", "properties": {}},
        },
    ]
