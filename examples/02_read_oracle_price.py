#!/usr/bin/env python3
"""
Example 02: Read oracle prices.

Fetches the live ERG/USD price from both Oracle Pool v2 and Spectrum DEX,
then compares them.

Usage:
    python examples/02_read_oracle_price.py
"""

from ergo_agent import ErgoNode
from ergo_agent.defi import OracleReader, SpectrumDEX

node = ErgoNode()

# Oracle Pool v2 price
oracle = OracleReader(node)
oracle_price = oracle.get_erg_usd_price()
raw_nanoerg = oracle.get_erg_usd_nanoerg_per_usd()

print("=== Oracle Pool v2 ===")
print(f"ERG/USD:          ${oracle_price:.4f}")
print(f"Raw R4 value:     {raw_nanoerg:,} nanoERG per USD")
print(f"Oracle box ID:    {oracle.get_oracle_box_id()[:16]}...")

# Spectrum DEX spot price
dex = SpectrumDEX(node)
dex_price = dex.get_erg_price_in_sigusd()

print(f"\n=== Spectrum DEX ===")
print(f"ERG/SigUSD:       ${dex_price:.4f}")

# Compare
spread_pct = abs(oracle_price - dex_price) / oracle_price * 100
print(f"\n=== Comparison ===")
print(f"Oracle vs DEX spread: {spread_pct:.2f}%")
if spread_pct > 5:
    print("[!] Large spread -- oracle may be lagging behind market price")
else:
    print("[OK] Prices are consistent")

dex.close()
node.close()
