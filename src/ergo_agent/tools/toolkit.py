"""
ErgoToolkit: the main entry point for AI agents.

This class wraps all Ergo capabilities into a unified interface that:
1. Exposes clean Python methods for all agent actions
2. Validates every action against SafetyConfig rules
3. Generates tool schemas for OpenAI, Anthropic, and LangChain

Usage:
    from ergo_agent import ErgoNode, Wallet
    from ergo_agent.tools import ErgoToolkit, SafetyConfig

    node = ErgoNode()
    wallet = Wallet.read_only("9f...")
    toolkit = ErgoToolkit(node, wallet)

    price = toolkit.get_erg_price()
    balance = toolkit.get_wallet_balance()

    # For LLM integration:
    tools = toolkit.to_openai_tools()    # list of OpenAI tool dicts
    tools = toolkit.to_anthropic_tools() # list of Anthropic tool dicts
    tools = toolkit.to_langchain_tools() # list of LangChain BaseTool
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ergo_agent.core.node import ErgoNode
from ergo_agent.core.wallet import Wallet
from ergo_agent.defi.oracle import OracleReader
from ergo_agent.defi.spectrum import SpectrumDEX
from ergo_agent.tools.safety import SafetyConfig, SafetyViolation

logger = logging.getLogger("ergo_agent.toolkit")


class ErgoToolkit:
    """
    Unified AI agent toolkit for the Ergo blockchain.

    All methods are safe to call directly from an LLM's tool-calling loop.
    Every state-changing action is validated by the SafetyConfig before execution.
    """

    def __init__(
        self,
        node: ErgoNode,
        wallet: Wallet,
        safety: SafetyConfig | None = None,
    ) -> None:
        self._node = node
        self._wallet = wallet
        self._safety = safety or SafetyConfig()
        self._oracle = OracleReader(node)
        self._dex = SpectrumDEX(node)

    # ------------------------------------------------------------------
    # Read-only actions (no safety checks needed)
    # ------------------------------------------------------------------

    def get_wallet_balance(self) -> dict[str, Any]:
        """
        Get the current ERG and token balance of the agent's wallet.

        Returns:
            dict with 'erg' (float), 'tokens' (list), and 'summary' (str)
        """
        balance = self._node.get_balance(self._wallet.address)
        return {
            "address": balance.address,
            "erg": balance.erg,
            "tokens": [
                {
                    "token_id": t.token_id,
                    "name": t.name or "Unknown",
                    "amount": t.amount_display,
                }
                for t in balance.tokens
            ],
            "summary": balance.to_agent_summary(),
        }

    def get_erg_price(self) -> dict[str, Any]:
        """
        Get the current ERG/USD price from the Ergo Oracle Pool.

        Returns:
            dict with 'erg_usd' (float) and 'source' (str)
        """
        try:
            price = self._oracle.get_erg_usd_price()
            return {
                "erg_usd": round(price, 4),
                "source": "Ergo Oracle Pool v2",
                "note": "On-chain oracle — live price from independent oracle operators",
            }
        except Exception as e:
            # Fallback to DEX spot price
            dex_price = self._dex.get_erg_price_in_sigusd()
            return {
                "erg_usd": round(dex_price, 4),
                "source": "Spectrum DEX spot price",
                "note": f"Oracle unavailable ({e}), using DEX spot price instead.",
            }

    def get_swap_quote(
        self,
        token_in: str,
        token_out: str,
        amount_erg: float | None = None,
        amount_token: int | None = None,
    ) -> dict[str, Any]:
        """
        Get a swap quote from Spectrum DEX without executing it.

        Args:
            token_in: Input token (e.g. "ERG", "SigUSD")
            token_out: Output token (e.g. "SigUSD", "ERG")
            amount_erg: Amount in ERG if token_in is ERG
            amount_token: Raw token amount if token_in is a token

        Returns:
            dict with expected output, price impact, and fee info
        """
        quote = self._dex.get_quote(token_in, token_out, amount_erg, amount_token)
        return {
            "token_in": token_in,
            "token_in_amount": amount_erg or amount_token,
            "token_out": token_out,
            "token_out_amount": quote.token_out_amount,
            "price": quote.price,
            "price_impact_pct": quote.price_impact_pct,
            "fee_pct": quote.fee_pct,
            "warning": "HIGH PRICE IMPACT" if quote.price_impact_pct > 2.0 else None,
        }

    def get_mempool_status(self) -> dict[str, Any]:
        """
        Check for pending transactions from this wallet.

        Returns:
            dict with pending transaction count and tx IDs
        """
        pending = self._node.get_mempool_transactions(self._wallet.address)
        return {
            "pending_count": len(pending),
            "pending_tx_ids": [tx.get("id", "") for tx in pending],
        }

    def get_safety_status(self) -> dict[str, Any]:
        """
        Get current safety limits and usage status.

        Returns:
            dict with remaining daily budget, rate limit status, etc.
        """
        return self._safety.get_status()

    # ------------------------------------------------------------------
    # State-changing actions (validated by safety layer)
    # ------------------------------------------------------------------

    def send_erg(self, to: str, amount_erg: float) -> dict[str, Any]:
        """
        Send ERG to an address.

        Args:
            to: Destination Ergo address
            amount_erg: Amount to send in ERG

        Returns:
            dict with tx_id (or dry_run confirmation)
        """
        self._safety.validate_rate_limit()
        self._safety.validate_send(amount_erg, to)

        if self._safety.dry_run:
            logger.info(f"[DRY RUN] Would send {amount_erg} ERG to {to}")
            return {"status": "dry_run", "would_send_erg": amount_erg, "to": to}

        if self._wallet.read_only:
            return {"status": "error", "message": "Wallet is read-only — cannot send transactions."}

        from ergo_agent.core.builder import TransactionBuilder
        tx = TransactionBuilder(self._node, self._wallet).send(to, amount_erg).build()
        signed = self._wallet.sign_transaction(tx, self._node)
        tx_id = self._node.submit_transaction(signed)

        self._safety.record_action(erg_spent=amount_erg)
        logger.info(f"Sent {amount_erg} ERG to {to} — tx: {tx_id}")
        return {"status": "submitted", "tx_id": tx_id, "amount_erg": amount_erg, "to": to}

    def swap_erg_for_token(
        self,
        token_out: str,
        amount_erg: float,
        max_slippage_pct: float = 1.0,
    ) -> dict[str, Any]:
        """
        Swap ERG for a token on Spectrum DEX.

        Args:
            token_out: Token to receive (e.g. "SigUSD")
            amount_erg: Amount of ERG to spend
            max_slippage_pct: Maximum acceptable price impact (default 1%)

        Returns:
            dict with quote info and tx_id (or dry_run confirmation)
        """
        self._safety.validate_rate_limit()
        self._safety.validate_send(amount_erg, "spectrum")

        # Get quote first
        quote = self._dex.get_quote("ERG", token_out, amount_erg=amount_erg)

        if quote.price_impact_pct > max_slippage_pct:
            return {
                "status": "rejected",
                "reason": f"Price impact {quote.price_impact_pct:.2f}% exceeds max slippage {max_slippage_pct:.2f}%",
                "quote": {
                    "token_out_amount": quote.token_out_amount,
                    "price_impact_pct": quote.price_impact_pct,
                },
            }

        if self._safety.dry_run:
            logger.info(f"[DRY RUN] Would swap {amount_erg} ERG for ~{quote.token_out_amount} {token_out}")
            return {
                "status": "dry_run",
                "would_swap_erg": amount_erg,
                "expected_out": quote.token_out_amount,
                "token_out": token_out,
                "price_impact_pct": quote.price_impact_pct,
            }

        if self._wallet.read_only:
            return {"status": "error", "message": "Wallet is read-only -- cannot execute swaps."}

        # Build Spectrum swap order transaction
        from ergo_agent.core.builder import TransactionBuilder

        order = self._dex.build_swap_order(
            token_in="ERG",
            token_out=token_out,
            amount_erg=amount_erg,
            return_address=self._wallet.address,
            max_slippage_pct=max_slippage_pct,
        )

        tx = (
            TransactionBuilder(self._node, self._wallet)
            .add_output_raw(
                ergo_tree=order["ergo_tree"],
                value_nanoerg=order["value_nanoerg"],
                tokens=order["tokens"],
                registers=order["registers"],
            )
            .build()
        )

        signed = self._wallet.sign_transaction(tx, self._node)
        tx_id = self._node.submit_transaction(signed)

        self._safety.record_action(erg_spent=amount_erg)
        logger.info(f"Swap order submitted: {amount_erg} ERG -> {token_out} -- tx: {tx_id}")
        return {
            "status": "submitted",
            "tx_id": tx_id,
            "amount_erg": amount_erg,
            "token_out": token_out,
            "expected_output": order["quote"]["expected_output"],
            "min_output": order["quote"]["min_output"],
            "price_impact_pct": order["quote"]["price_impact_pct"],
        }


    # ------------------------------------------------------------------
    # Tool schema generators
    # ------------------------------------------------------------------

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """Generate OpenAI function-calling tool definitions."""
        from ergo_agent.tools.openai_tools import build_openai_tools
        return build_openai_tools(self)

    def to_anthropic_tools(self) -> list[dict[str, Any]]:
        """Generate Anthropic tool-use definitions."""
        from ergo_agent.tools.anthropic_tools import build_anthropic_tools
        return build_anthropic_tools(self)

    def to_langchain_tools(self) -> list[Any]:
        """Generate LangChain BaseTool instances."""
        from ergo_agent.tools.langchain_tools import build_langchain_tools
        return build_langchain_tools(self)

    def execute_tool(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """
        Execute a tool by name with given inputs.
        Used by LLM frameworks to dispatch tool calls.

        Returns:
            str: JSON-encoded result
        """
        tool_map = {
            "get_wallet_balance": lambda _: self.get_wallet_balance(),
            "get_erg_price": lambda _: self.get_erg_price(),
            "get_swap_quote": lambda i: self.get_swap_quote(**i),
            "get_mempool_status": lambda _: self.get_mempool_status(),
            "get_safety_status": lambda _: self.get_safety_status(),
            "send_erg": lambda i: self.send_erg(**i),
            "swap_erg_for_token": lambda i: self.swap_erg_for_token(**i),
        }

        fn = tool_map.get(tool_name)
        if not fn:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

        try:
            result = fn(tool_input)
            return json.dumps(result, indent=2)
        except SafetyViolation as e:
            logger.warning(f"Safety violation on {tool_name}: {e}")
            return json.dumps({"error": "safety_violation", "message": str(e)})
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}")
            return json.dumps({"error": str(e)})
