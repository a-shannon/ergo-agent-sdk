"""
OracleReader: reads live price feeds from Ergo Oracle Pool v2.

The Oracle Pool v2 is existing Ergo infrastructure — no new contracts needed.
This adapter just reads the pool box and decodes the price from register R4.

Reference: https://github.com/ergoplatform/oracle-core
Oracle Pool v2 spec: https://github.com/ergoplatform/eips/blob/master/eip-0023.md

How it works:
- An oracle pool box has a singleton NFT identifying it
- Register R4 contains the current aggregated price (nanoERG per data unit)
- Multiple dApps (SigmaUSD, etc.) read this same box as a data input
"""

from __future__ import annotations

from ergo_agent.core.models import NANOERG_PER_ERG
from ergo_agent.core.node import ErgoNode

# Oracle Pool mainnet NFT IDs (these are fixed, deployed on mainnet)
# Source: https://github.com/ergoplatform/oracle-core/blob/master/docs/oracle-pool-v2.md
ORACLE_NFT_IDS = {
    # ERG/USD pool — price in nanoERG per USD cent
    "erg_usd": "011d3364de07e5a26f0c4eef0852cddb387039a921b7154ef3cab22c6eda887f",
    # ERG/XAU (gold) pool
    "erg_xau": "74251ce2cb4eb2024a1a155e19ad1d1f58ff8b9e6eb034a3bb1fd58802757d23",
}




class OracleReader:
    """
    Read live prices from the Ergo Oracle Pool v2.

    Usage:
        oracle = OracleReader(node)
        price = oracle.get_erg_usd_price()  # e.g. 0.87
        print(f"ERG/USD: ${price:.2f}")
    """

    def __init__(self, node: ErgoNode) -> None:
        self._node = node

    def get_erg_usd_price(self) -> float:
        """
        Return the current ERG/USD price from the oracle pool.

        The oracle R4 value is nanoERG per 1 USD.
        We convert: price_usd = NANOERG_PER_ERG / nanoERG_per_USD

        Returns:
            float: ERG price in USD (e.g. 0.31 means 1 ERG = $0.31)
        """
        box = self._node.get_oracle_pool_box(ORACLE_NFT_IDS["erg_usd"])
        r4 = box.additional_registers.get("R4")
        if r4 is None:
            raise ValueError("Oracle pool box missing R4 price register.")
        nanoerg_per_usd = self._extract_register_long(r4)
        # 1 USD costs nanoerg_per_usd nanoERG, so 1 ERG costs:
        price_usd = NANOERG_PER_ERG / nanoerg_per_usd
        return price_usd

    def get_erg_usd_nanoerg_per_usd(self) -> int:
        """
        Return the raw oracle value: nanoERG per 1 USD.
        This is the value used directly in ErgoScript contracts.
        """
        box = self._node.get_oracle_pool_box(ORACLE_NFT_IDS["erg_usd"])
        r4 = box.additional_registers.get("R4")
        if r4 is None:
            raise ValueError("Oracle pool box missing R4 price register.")
        return self._extract_register_long(r4)

    # Backward-compatible alias
    get_erg_usd_nanoerg_per_cent = get_erg_usd_nanoerg_per_usd

    def get_oracle_box_id(self, pair: str = "erg_usd") -> str:
        """
        Return the current oracle pool box ID.
        Used when adding an oracle box as a data input to a transaction.
        """
        nft_id = ORACLE_NFT_IDS.get(pair)
        if not nft_id:
            raise ValueError(f"Unknown oracle pair: {pair}. Available: {list(ORACLE_NFT_IDS)}")
        box = self._node.get_oracle_pool_box(nft_id)
        return box.box_id

    def get_all_prices(self) -> dict[str, float | None]:
        """
        Return all available oracle prices.

        Returns:
            dict: {"erg_usd": 0.87, "erg_xau": ...}
        """
        results: dict[str, float | None] = {}
        for pair in ORACLE_NFT_IDS:
            try:
                if pair == "erg_usd":
                    results[pair] = self.get_erg_usd_price()
                else:
                    results[pair] = None  # Other pairs TBD in v0.2
            except Exception:
                results[pair] = None
        return results

    @staticmethod
    def _extract_register_long(register_value: str | dict) -> int:
        """
        Extract a Long value from a register, handling both API formats.

        The Explorer API may return registers in two formats:
        1. Raw hex string: "058084af5f"
        2. Rich dict: {"serializedValue": "05beedecf517", "sigmaType": "SLong",
                        "renderedValue": "3210582879"}

        We prefer renderedValue when available (no decoding needed),
        and fall back to the ZigZag decoder for raw hex.
        """
        if isinstance(register_value, dict):
            # Rich format — use renderedValue if available
            rendered = register_value.get("renderedValue")
            if rendered is not None:
                return int(rendered)
            # Fall back to serializedValue
            hex_value = register_value.get("serializedValue", "")
        else:
            hex_value = register_value

        return OracleReader._decode_slong(hex_value)

    @staticmethod
    def _decode_slong(hex_value: str) -> int:
        """
        Decode Ergo's SLong register encoding.

        ErgoScript serializes Long values with a type prefix byte (0x05)
        followed by a ZigZag-encoded VLong.

        Example: "058084af5f" → type 0x05 (Long) + ZigZag VLong bytes
        """
        if hex_value.startswith("05"):
            data = bytes.fromhex(hex_value[2:])  # skip type byte
        else:
            data = bytes.fromhex(hex_value)

        # Read ZigZag-encoded VarLong
        result = 0
        shift = 0
        for byte in data:
            result |= (byte & 0x7F) << shift
            if not (byte & 0x80):
                break
            shift += 7

        # Decode ZigZag: n = (result >>> 1) ^ -(result & 1)
        decoded = (result >> 1) ^ -(result & 1)
        return decoded
