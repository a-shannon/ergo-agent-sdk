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
                "name": "privacy_pool_get_status",
                "description": (
                    "Get the current status of a privacy MasterPoolBox. "
                    "Returns deposit count, privacy score, anonymity assessment, and ERG balance."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pool_box_id": {"type": "string", "description": "The box ID of the MasterPoolBox."},
                    },
                    "required": ["pool_box_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "privacy_pool_deposit",
                "description": (
                    "Create a privacy pool deposit intent. Generates a fresh Pedersen Commitment "
                    "and returns the blinding factor (secret). The blinding_factor MUST be saved — "
                    "it is the ONLY way to later withdraw your funds."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tier": {
                            "type": "string",
                            "description": "Pool tier: '1_erg', '10_erg', or '100_erg'.",
                            "enum": ["1_erg", "10_erg", "100_erg"],
                        },
                    },
                    "required": ["tier"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "privacy_pool_withdraw",
                "description": (
                    "Create a privacy pool withdrawal intent using DHTuple ring signatures. "
                    "Requires the blinding factor from the original deposit, the pool tier, "
                    "a destination address, and decoy commitments from the pool."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "blinding_factor_hex": {
                            "type": "string",
                            "description": "The hex blinding factor from the deposit.",
                        },
                        "tier": {
                            "type": "string",
                            "description": "Pool tier: '1_erg', '10_erg', or '100_erg'.",
                            "enum": ["1_erg", "10_erg", "100_erg"],
                        },
                        "recipient_address": {
                            "type": "string",
                            "description": "Destination Ergo address (starts with '9').",
                        },
                        "decoy_commitments": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of decoy commitment hex strings from the pool's deposit tree.",
                        },
                    },
                    "required": ["blinding_factor_hex", "tier", "recipient_address", "decoy_commitments"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "privacy_pool_export_view_key",
                "description": (
                    "Export a privacy View Key for compliance or audit disclosure. "
                    "Allows an auditor to verify a specific deposit without ZK proofs."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "blinding_factor_hex": {
                            "type": "string",
                            "description": "The hex blinding factor from the deposit.",
                        },
                        "tier": {
                            "type": "string",
                            "description": "Pool tier: '1_erg', '10_erg', or '100_erg'.",
                            "enum": ["1_erg", "10_erg", "100_erg"],
                        },
                    },
                    "required": ["blinding_factor_hex", "tier"],
                },
            },
        },
    ]
