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
            "name": "send_funds",
            "description": "Send ERG and optionally multiple tokens to an Ergo address. Subject to safety limits.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Destination Ergo address"},
                    "amount_erg": {"type": "number", "description": "Amount in ERG"},
                    "tokens": {
                        "type": "object",
                        "description": "Optional dictionary mapping Token IDs to their raw integer amounts.",
                        "additionalProperties": {
                            "type": "integer"
                        }
                    },
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
        {
            "name": "get_sigmausd_state",
            "description": "Get the current state of the AgeUSD protocol (SigmaUSD/SigmaRSV). Returns Reserve Ratio and Prices.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "get_rosen_bridge_status",
            "description": "Get the current TVL and supported chains for the Rosen Bridge on Ergo.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "mint_token",
            "description": "Mint a new native Ergo token (EIP-004 compliant).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Token name"},
                    "description": {"type": "string", "description": "Token description"},
                    "amount": {"type": "integer", "description": "Total supply"},
                    "decimals": {"type": "integer", "description": "Decimal places"},
                },
                "required": ["name", "description", "amount", "decimals"],
            },
        },
        {
            "name": "get_privacy_pools",
            "description": "Scan the blockchain for active privacy pool privacy pools.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "denomination": {"type": "integer", "description": "The token denomination (e.g., 100, 1000)"},
                },
                "required": ["denomination"],
            },
        },
        {
            "name": "deposit_to_privacy_pool",
            "description": "Deposit a privacy pool note denomination into a privacy pool to enter the ring.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pool_id": {"type": "string", "description": "The UTXO ID of the pool"},
                    "denomination": {"type": "integer", "description": "The note denomination jumping into the pool."},
                },
                "required": ["pool_id", "denomination"],
            },
        },
        {
            "name": "withdraw_from_privacy_pool",
            "description": "Withdraw a privacy pool note from a privacy pool using an autonomous ring signature!",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pool_id": {"type": "string", "description": "The privacy pool to withdraw from."},
                    "recipient_address": {"type": "string", "description": "Destination EIP-41 stealth address."},
                    "key_image": {"type": "string", "description": "Hex string key image preventing double withdrawal."},
                },
                "required": ["pool_id", "recipient_address", "key_image"],
            },
        },
    ]
