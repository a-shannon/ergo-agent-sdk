"""LangChain tool wrappers for ErgoToolkit."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ergo_agent.tools.toolkit import ErgoToolkit


def build_langchain_tools(toolkit: ErgoToolkit) -> list[Any]:
    """
    Return a list of LangChain BaseTool instances.
    Requires: pip install ergo-agent-sdk[langchain]
    """
    try:
        from langchain_core.tools import tool as lc_tool
    except ImportError:
        raise ImportError(
            "LangChain integration requires: pip install ergo-agent-sdk[langchain]"
        ) from None

    @lc_tool
    def get_wallet_balance() -> str:
        """Get the current ERG and token balance of the agent's Ergo wallet."""
        import json
        return json.dumps(toolkit.get_wallet_balance())

    @lc_tool
    def get_erg_price() -> str:
        """Get the current ERG/USD price from the Ergo Oracle Pool (on-chain)."""
        import json
        return json.dumps(toolkit.get_erg_price())

    @lc_tool
    def get_swap_quote(token_in: str, token_out: str, amount_erg: float = 0.0) -> str:
        """
        Get a Spectrum DEX swap quote without executing it.
        token_in: input token symbol (e.g. 'ERG', 'SigUSD')
        token_out: output token symbol
        amount_erg: amount in ERG if token_in is ERG
        """
        import json
        return json.dumps(toolkit.get_swap_quote(
            token_in=token_in,
            token_out=token_out,
            amount_erg=amount_erg if amount_erg > 0 else None,
        ))

    @lc_tool
    def send_erg(to: str, amount_erg: float) -> str:
        """
        Send ERG to an Ergo address.
        to: destination address (starts with '9')
        amount_erg: amount to send in ERG
        """
        import json
        return json.dumps(toolkit.send_erg(to=to, amount_erg=amount_erg))

    @lc_tool
    def swap_erg_for_token(token_out: str, amount_erg: float, max_slippage_pct: float = 1.0) -> str:
        """
        Swap ERG for a token on Spectrum DEX.
        token_out: token to receive (e.g. 'SigUSD')
        amount_erg: ERG to spend
        max_slippage_pct: maximum price impact in percent (default 1.0)
        """
        import json
        return json.dumps(toolkit.swap_erg_for_token(
            token_out=token_out,
            amount_erg=amount_erg,
            max_slippage_pct=max_slippage_pct,
        ))

    @lc_tool
    def get_mempool_status() -> str:
        """Check for pending (unconfirmed) transactions from this wallet."""
        import json
        return json.dumps(toolkit.get_mempool_status())

    @lc_tool
    def get_safety_status() -> str:
        """Get current safety limits: remaining daily budget and rate limit status."""
        import json
        return json.dumps(toolkit.get_safety_status())

    return [
        get_wallet_balance,
        get_erg_price,
        get_swap_quote,
        send_erg,
        swap_erg_for_token,
        get_mempool_status,
        get_safety_status,
    ]
