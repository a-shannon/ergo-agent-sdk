"""OpenAI function-calling tool definitions for ErgoToolkit."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ergo_agent.tools.toolkit import ErgoToolkit


def build_openai_tools(toolkit: ErgoToolkit) -> list[dict[str, Any]]:
    """Return a list of OpenAI function-calling tool definitions."""
    return [
        {
            "type": "function",
            "function": {
                "name": "get_wallet_balance",
                "description": "Get the current ERG and token balance of the agent's Ergo wallet.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_erg_price",
                "description": (
                    "Get the current ERG/USD price from the Ergo Oracle Pool v2 (on-chain). "
                    "Returns the price in USD per 1 ERG."
                ),
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_swap_quote",
                "description": (
                    "Get a swap quote from Spectrum DEX without executing it. "
                    "Use this to check the expected output amount and price impact before swapping."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "token_in": {
                            "type": "string",
                            "description": "Input token symbol (e.g. 'ERG', 'SigUSD', 'SigRSV')",
                        },
                        "token_out": {
                            "type": "string",
                            "description": "Output token symbol (e.g. 'SigUSD', 'ERG')",
                        },
                        "amount_erg": {
                            "type": "number",
                            "description": "Amount in ERG to swap (required if token_in is 'ERG')",
                        },
                        "amount_token": {
                            "type": "integer",
                            "description": "Raw token amount to swap (required if token_in is a token)",
                        },
                    },
                    "required": ["token_in", "token_out"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "send_funds",
                "description": (
                    "Send ERG and optionally multiple tokens to an Ergo address. "
                    "Subject to safety limits (max per transaction, daily cap, rate limit). "
                    "Will be rejected if limits are exceeded."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to": {
                            "type": "string",
                            "description": "Destination Ergo address (starts with '9')",
                        },
                        "amount_erg": {
                            "type": "number",
                            "description": "Amount to send in ERG",
                        },
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
        },
        {
            "type": "function",
            "function": {
                "name": "swap_erg_for_token",
                "description": (
                    "Swap ERG for a token on Spectrum DEX. "
                    "The swap will be rejected if the price impact exceeds max_slippage_pct. "
                    "Always get a quote first with get_swap_quote."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "token_out": {
                            "type": "string",
                            "description": "Token to receive (e.g. 'SigUSD')",
                        },
                        "amount_erg": {
                            "type": "number",
                            "description": "Amount of ERG to spend",
                        },
                        "max_slippage_pct": {
                            "type": "number",
                            "description": "Maximum acceptable price impact in percent (default: 1.0)",
                        },
                    },
                    "required": ["token_out", "amount_erg"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_mempool_status",
                "description": "Check for pending (unconfirmed) transactions from this wallet.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_safety_status",
                "description": (
                    "Get the current safety limits and usage status. "
                    "Check this to know remaining daily budget and rate limit before acting."
                ),
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "mint_token",
                "description": "Mint a new native Ergo token (EIP-004 compliant).",
                "parameters": {
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
        },
        {
            "type": "function",
            "function": {
                "name": "get_cash_pools",
                "description": "Scan the blockchain for active $CASH v3 privacy pools.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "denomination": {"type": "integer", "description": "The token denomination (e.g., 100, 1000)"},
                    },
                    "required": ["denomination"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "deposit_cash_to_pool",
                "description": "Deposit a $CASH note denomination into a privacy pool to enter the ring.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pool_id": {"type": "string", "description": "The UTXO ID of the pool"},
                        "denomination": {"type": "integer", "description": "The note denomination jumping into the pool."},
                    },
                    "required": ["pool_id", "denomination"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "withdraw_cash_privately",
                "description": "Withdraw a $CASH note from a privacy pool using an autonomous ring signature!",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pool_id": {"type": "string", "description": "The privacy pool to withdraw from."},
                        "recipient_address": {"type": "string", "description": "Destination EIP-41 stealth address."},
                        "key_image": {"type": "string", "description": "Hex string key image preventing double withdrawal."},
                    },
                    "required": ["pool_id", "recipient_address", "key_image"],
                },
            },
        },
    ]
