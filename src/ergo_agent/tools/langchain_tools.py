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
    def send_funds(to: str, amount_erg: float, tokens: dict[str, int] | None = None) -> str:
        """
        Send ERG and optionally multiple tokens to an Ergo address.
        to: destination address (starts with '9')
        amount_erg: amount to send in ERG
        tokens: optional dict mapping token IDs to amounts
        """
        import json
        return json.dumps(toolkit.send_funds(to=to, amount_erg=amount_erg, tokens=tokens))

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

    @lc_tool
    def get_sigmausd_state() -> str:
        """Get the current State of the SigmaUSD Protocol (reserve ratio and prices)."""
        import json
        return json.dumps(toolkit.get_sigmausd_state())

    @lc_tool
    def get_rosen_bridge_status() -> str:
        """Get the current global TVL and supported chains of the Rosen Bridge."""
        import json
        return json.dumps(toolkit.get_rosen_bridge_status())

    @lc_tool
    def mint_token(name: str, description: str, amount: int, decimals: int) -> str:
        """
        Mint a new native Ergo token (EIP-004 compliant).
        name: Name of the new token (e.g. 'AgentCoin')
        description: Short description of the token
        amount: Total integer supply to mint
        decimals: Number of decimal places (e.g. 0 for NFTs, 4 for standard)
        """
        import json
        return json.dumps(toolkit.mint_token(
            name=name, description=description, amount=amount, decimals=decimals
        ))

    @lc_tool
    def privacy_pool_get_status(pool_box_id: str) -> str:
        """Get the current status of a privacy MasterPoolBox (deposit count, privacy score, anonymity assessment)."""
        import json
        return json.dumps(toolkit.privacy_pool_get_status(pool_box_id=pool_box_id))

    @lc_tool
    def privacy_pool_deposit(tier: str) -> str:
        """Create a privacy pool deposit intent. Returns blinding_factor — MUST be saved for withdrawal.
        tier: '1_erg', '10_erg', or '100_erg'"""
        import json
        return json.dumps(toolkit.privacy_pool_deposit(tier=tier))

    @lc_tool
    def privacy_pool_withdraw(blinding_factor_hex: str, tier: str, recipient_address: str, decoy_commitments: list[str]) -> str:
        """Create a privacy pool withdrawal intent using DHTuple ring signatures.
        blinding_factor_hex: hex blinding factor from deposit
        tier: pool tier ('1_erg', '10_erg', '100_erg')
        recipient_address: destination Ergo address
        decoy_commitments: list of decoy commitment hexes from the pool"""
        import json
        return json.dumps(toolkit.privacy_pool_withdraw(
            blinding_factor_hex=blinding_factor_hex,
            tier=tier,
            recipient_address=recipient_address,
            decoy_commitments=decoy_commitments,
        ))

    @lc_tool
    def privacy_pool_export_view_key(blinding_factor_hex: str, tier: str) -> str:
        """Export a privacy View Key for compliance/audit disclosure.
        blinding_factor_hex: hex blinding factor from deposit
        tier: pool tier"""
        import json
        return json.dumps(toolkit.privacy_pool_export_view_key(
            blinding_factor_hex=blinding_factor_hex,
            tier=tier,
        ))

    return [
        get_wallet_balance,
        get_erg_price,
        get_swap_quote,
        send_funds,
        swap_erg_for_token,
        get_mempool_status,
        get_safety_status,
        get_sigmausd_state,
        get_rosen_bridge_status,
        mint_token,
        privacy_pool_get_status,
        privacy_pool_deposit,
        privacy_pool_withdraw,
        privacy_pool_export_view_key,
    ]
