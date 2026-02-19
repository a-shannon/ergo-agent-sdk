"""
SpectrumDEX: adapter for Spectrum Finance (the main Ergo DEX).

Spectrum Finance uses AMM pool boxes following the Ergo eUTXO model.
Each pool is a box containing both token reserves, protected by a script
that enforces the x*y=k invariant.

This adapter:
1. Reads live market data from the Spectrum price-tracking API
2. Computes swap quotes (output amount given input)
3. Constructs swap order boxes (the actual swap transaction input)

API: https://api.spectrum.fi/v1/price-tracking/markets
Reference: https://github.com/spectrum-finance/ergo-dex
"""

from __future__ import annotations

from typing import Any

import httpx

from ergo_agent.core.models import NANOERG_PER_ERG, SwapQuote
from ergo_agent.core.node import ErgoNode

# Spectrum Finance public API — read-only price/pool data
SPECTRUM_API = "https://api.spectrum.fi"

# Well-known token IDs on mainnet
WELL_KNOWN_TOKENS = {
    "ERG": "0000000000000000000000000000000000000000000000000000000000000000",  # native ERG
    "SigUSD": "03faf2cb329f2e90d6d23b58d91bbb6c046aa143261cc21f52fbe2824bfcbf04",
    "SigRSV": "003bd19d0187117f130b62e1bcab0939929ff5c7709f843c5c4dd158949285d0",
    "SPF": "9a06d9e545a41fd51eeffc5e20d818073bf820c635e2a9d922269913e0de369d",
}

# Reverse map: token ID → ticker
TOKEN_TICKERS = {v: k for k, v in WELL_KNOWN_TOKENS.items()}

# Token decimal places
TOKEN_DECIMALS = {
    "ERG": 9,
    "SigUSD": 2,
    "SigRSV": 0,
    "SPF": 6,
}


class SpectrumDEXError(Exception):
    pass


class Market:
    """Represents a Spectrum trading pair from the price-tracking API."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @property
    def market_id(self) -> str:
        return str(self._data.get("id", ""))

    @property
    def base_id(self) -> str:
        return str(self._data.get("baseId", ""))

    @property
    def base_symbol(self) -> str:
        return str(self._data.get("baseSymbol", ""))

    @property
    def quote_id(self) -> str:
        return str(self._data.get("quoteId", ""))

    @property
    def quote_symbol(self) -> str:
        return str(self._data.get("quoteSymbol", ""))

    @property
    def last_price(self) -> float:
        return float(self._data.get("lastPrice", 0.0))

    @property
    def base_volume_raw(self) -> int:
        vol = self._data.get("baseVolume", {})
        return int(vol.get("value", 0))

    @property
    def quote_volume_raw(self) -> int:
        vol = self._data.get("quoteVolume", {})
        return int(vol.get("value", 0))

    @property
    def base_decimals(self) -> int:
        vol = self._data.get("baseVolume", {})
        units = vol.get("units", {}).get("asset", {})
        return int(units.get("decimals", 0))

    @property
    def quote_decimals(self) -> int:
        vol = self._data.get("quoteVolume", {})
        units = vol.get("units", {}).get("asset", {})
        return int(units.get("decimals", 0))

    def __repr__(self) -> str:
        return f"Market({self.base_symbol}/{self.quote_symbol}, price={self.last_price:.4f})"


# Keep Pool as a backward-compatible alias
Pool = Market


class SpectrumDEX:
    """
    Adapter for Spectrum Finance DEX on Ergo.

    Usage:
        dex = SpectrumDEX(node)
        markets = dex.get_pools()
        quote = dex.get_quote(token_in="ERG", token_out="SigUSD", amount_erg=10.0)
        print(f"You get: {quote.token_out_amount} SigUSD")
    """

    def __init__(
        self,
        node: ErgoNode,
        api_url: str = SPECTRUM_API,
        timeout: float = 15.0,
    ) -> None:
        self._node = node
        self._api = api_url.rstrip("/")
        self._http = httpx.Client(timeout=timeout)

    def get_pools(self, offset: int = 0, limit: int = 100) -> list[Market]:
        """
        Fetch active Spectrum markets (trading pairs).

        Returns:
            list[Market]: sorted by volume descending
        """
        try:
            resp = self._http.get(
                f"{self._api}/v1/price-tracking/markets",
            )
            resp.raise_for_status()
            all_markets = [Market(m) for m in resp.json()]
            # Filter out markets with zero volume and apply pagination
            active = [m for m in all_markets if m.base_volume_raw > 0 or m.last_price > 0]
            return active[offset:offset + limit]
        except httpx.HTTPError as e:
            raise SpectrumDEXError(f"Failed to fetch markets: {e}") from e

    def get_pool(self, token_x: str, token_y: str) -> Market:
        """
        Find the best market for a given token pair.

        Args:
            token_x: token name or ID (e.g. "ERG" or "SigUSD")
            token_y: token name or ID

        Returns:
            Market: the matching trading pair
        """
        token_x_id = WELL_KNOWN_TOKENS.get(token_x, token_x)
        token_y_id = WELL_KNOWN_TOKENS.get(token_y, token_y)

        markets = self.get_pools(limit=500)
        matching = [
            m for m in markets
            if (m.base_id == token_x_id and m.quote_id == token_y_id)
            or (m.base_id == token_y_id and m.quote_id == token_x_id)
        ]

        if not matching:
            raise SpectrumDEXError(f"No market found for {token_x}/{token_y}.")

        # Return the one with most volume
        return max(matching, key=lambda m: m.base_volume_raw)

    def get_quote(
        self,
        token_in: str,
        token_out: str,
        amount_erg: float | None = None,
        amount_token: int | None = None,
    ) -> SwapQuote:
        """
        Get a swap quote for a given input.

        This uses the Spectrum API's last price data to estimate the output.
        Note: for exact on-chain output, pool box reserves should be read
        directly. The API price gives a good approximation.

        Args:
            token_in: input token (name or ID, use "ERG" for native ERG)
            token_out: output token (name or ID)
            amount_erg: if token_in is ERG, specify amount in ERG
            amount_token: if token_in is a token, specify raw amount

        Returns:
            SwapQuote with expected output amount and price impact
        """
        market = self.get_pool(token_in, token_out)

        # Determine input amount in raw units
        if token_in == "ERG" and amount_erg is not None:
            amount_in = int(amount_erg * NANOERG_PER_ERG)
        elif amount_token is not None:
            amount_in = amount_token
        else:
            raise SpectrumDEXError("Specify either amount_erg or amount_token.")

        # Determine the direction and use lastPrice as rate
        token_in_id = WELL_KNOWN_TOKENS.get(token_in, token_in)
        token_out_id = WELL_KNOWN_TOKENS.get(token_out, token_out)

        # Get decimal info
        in_decimals = self._get_decimals(token_in, market)
        out_decimals = self._get_decimals(token_out, market)

        # Calculate output using lastPrice
        if market.base_id == token_in_id:
            # base → quote: output = input * lastPrice
            price = market.last_price
        else:
            # quote → base: output = input / lastPrice
            price = 1.0 / market.last_price if market.last_price > 0 else 0

        # Normalize input to human units, apply price, then convert back to raw units
        amount_in_human = amount_in / (10 ** in_decimals)
        amount_out_human = amount_in_human * price

        # Apply a 0.3% fee (standard Spectrum fee)
        fee_pct = 0.3
        amount_out_with_fee = amount_out_human * (1 - fee_pct / 100)
        amount_out = int(amount_out_with_fee * (10 ** out_decimals))

        return SwapQuote(
            pool_id=market.market_id,
            token_in_id=token_in_id,
            token_in_amount=amount_in,
            token_out_id=token_out_id,
            token_out_amount=amount_out,
            price_impact_pct=0.0,  # API doesn't provide pool-level impact data
            fee_pct=fee_pct,
        )

    def _get_decimals(self, token: str, market: Market) -> int:
        """Get decimal places for a token from market data or known defaults."""
        # Check known tokens first
        if token in TOKEN_DECIMALS:
            return TOKEN_DECIMALS[token]
        # Check market data
        token_id = WELL_KNOWN_TOKENS.get(token, token)
        if market.base_id == token_id:
            return market.base_decimals
        if market.quote_id == token_id:
            return market.quote_decimals
        return 0

    def get_erg_price_in_sigusd(self) -> float:
        """
        Convenience: get ERG/USD price from DEX pool directly.
        Note: use OracleReader for the canonical on-chain oracle price.
        """
        try:
            market = self.get_pool("ERG", "SigUSD")
            # lastPrice is already in human-readable format
            if market.base_id == WELL_KNOWN_TOKENS["ERG"]:
                return market.last_price
            elif market.quote_id == WELL_KNOWN_TOKENS["ERG"]:
                return 1.0 / market.last_price if market.last_price > 0 else 0.0
            return 0.0
        except SpectrumDEXError:
            return 0.0

    def build_swap_order(
        self,
        token_in: str,
        token_out: str,
        amount_erg: float,
        return_address: str,
        min_output: int | None = None,
        max_slippage_pct: float = 1.0,
    ) -> dict[str, Any]:
        """
        Build a Spectrum DEX swap order dict for TransactionBuilder.add_output_raw().

        On Ergo's eUTXO model, DEX swaps work via order boxes:
        1. User creates an order box containing ERG + order parameters
        2. Spectrum off-chain bots detect this box and execute the swap
        3. User receives output tokens in a new box at their address

        Args:
            token_in: input token name (e.g. "ERG")
            token_out: output token name (e.g. "SigUSD")
            amount_erg: amount of ERG to swap
            return_address: address to receive output tokens
            min_output: minimum acceptable output amount (auto-calculated if None)
            max_slippage_pct: max slippage for auto min_output calculation

        Returns:
            dict with 'ergo_tree', 'value_nanoerg', 'tokens', 'registers'
            ready for TransactionBuilder.add_output_raw()
        """
        from ergo_agent.core.address import address_to_ergo_tree

        # Get quote for the swap
        quote = self.get_quote(token_in, token_out, amount_erg=amount_erg)

        # Calculate minimum output with slippage
        if min_output is None:
            min_output = int(quote.token_out_amount * (1 - max_slippage_pct / 100))

        # Get the ErgoTree for the return address
        return_ergo_tree = address_to_ergo_tree(return_address)

        # Token IDs
        token_out_id = WELL_KNOWN_TOKENS.get(token_out, token_out)

        # Spectrum swap order ErgoTree
        swap_order_ergo_tree = self._get_swap_contract_ergo_tree(token_in, token_out)

        # Value: input ERG amount + execution fee for bots
        execution_fee = 2_000_000  # 0.002 ERG for bot execution
        value_nanoerg = int(amount_erg * NANOERG_PER_ERG) + execution_fee

        # Registers encode the order parameters:
        # R4: return ErgoTree (where to send output tokens)
        # R5: minimum output amount (SLong encoded)
        # R6: execution fee nanoERG
        registers = {
            "R4": _encode_byte_array_register(bytes.fromhex(return_ergo_tree)),
            "R5": _encode_slong_register(min_output),
            "R6": _encode_slong_register(execution_fee),
        }

        return {
            "ergo_tree": swap_order_ergo_tree,
            "value_nanoerg": value_nanoerg,
            "tokens": [],  # For ERG->Token swaps, no input tokens needed
            "registers": registers,
            "quote": {
                "pool_id": quote.pool_id,
                "expected_output": quote.token_out_amount,
                "min_output": min_output,
                "token_out_id": token_out_id,
                "price_impact_pct": quote.price_impact_pct,
                "fee_pct": quote.fee_pct,
            },
        }

    def _get_swap_contract_ergo_tree(self, token_in: str, token_out: str) -> str:
        """
        Get the ErgoTree for the appropriate Spectrum swap contract.

        Spectrum has different contracts for:
        - N2T: native ERG to token swaps
        - T2T: token to token swaps
        """
        # Spectrum N2T (ERG -> Token) swap contract ErgoTree
        # This is a well-known, audited contract on Ergo mainnet
        # Source: https://github.com/spectrum-finance/ergo-dex
        if token_in == "ERG":
            # N2T swap order contract
            return (
                "19c0062904000400040204020404040404060406040804080404040204000400"
                "040204020400040a050005000404040204020e20"
                + WELL_KNOWN_TOKENS.get(token_out, token_out)
                + "0400040404020402040204040400050005feffffffffffffffff01050005000580"
                "897a04000580897a040005040004000100d806d601b2a5730000d602e4c6a7"
                "0410d603e4c6a70510d604e4c6a70610d605b2db63087201730100d606b2"
                "db6308a7730200ea02d1ededed93b1a57303938cb2db63087203730400017305"
                "93c2b2a5730600d801d607e4c68c050604ededed93e4c68c0706049591"
                "a37307d19683020193a38cc7b2a5730800001793c1b2a5730900d804d607"
                "e4c6a70410d608b2a5730a00d609b2db63087208730b00d60ae4c68c090604"
                "edededed93cbc27208730c93d0e4c68c090504e4c6a7040e93e4c6"
                "8c090404e4c6a70804"
            )
        # T2T swap: would need token_in ID embedded in the contract
        raise SpectrumDEXError(
            f"Only ERG->Token swaps are currently supported. "
            f"T2T ({token_in}->{token_out}) coming in v0.2."
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> SpectrumDEX:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


# ------------------------------------------------------------------
# Register encoding helpers (Ergo Sigma serialization)
# ------------------------------------------------------------------

def _encode_slong_register(value: int) -> str:
    """Encode an integer as an Ergo SLong register value (hex string)."""
    # SLong type prefix = 0x05
    # ZigZag encoding: (n << 1) ^ (n >> 63)
    zigzag = (value << 1) ^ (value >> 63)
    # VLQ encoding
    result = [0x05]  # SLong type byte
    while zigzag > 0x7F:
        result.append((zigzag & 0x7F) | 0x80)
        zigzag >>= 7
    result.append(zigzag & 0x7F)
    return bytes(result).hex()


def _encode_byte_array_register(data: bytes) -> str:
    """Encode a byte array as an Ergo register value (hex string)."""
    # Type prefix 0x0e = Coll[Byte]
    length = len(data)
    # VLQ encode the length
    vlq_len = []
    n = length
    while n > 0x7F:
        vlq_len.append((n & 0x7F) | 0x80)
        n >>= 7
    vlq_len.append(n & 0x7F)
    return bytes([0x0e] + vlq_len).hex() + data.hex()
