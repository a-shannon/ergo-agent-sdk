#!/usr/bin/env python3
"""
Example 09: Spectrum DEX market scanner.

Scans all Spectrum DEX markets and displays top pools by trading
volume, including token pairs and last price.

Usage:
    python examples/09_dex_scanner.py
"""

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from ergo_agent import ErgoNode
from ergo_agent.defi import SpectrumDEX

node = ErgoNode()
dex = SpectrumDEX(node)

markets = dex.get_pools()

print("=" * 60)
print("  SPECTRUM DEX MARKET SCANNER")
print("=" * 60)
print(f"  Total active markets: {len(markets)}")
print("-" * 60)
print(f"  {'Pair':<25} {'Last Price':>12} {'Base Vol':>12}")
print("-" * 60)

# Sort by base volume (descending), show top 20
sorted_markets = sorted(markets, key=lambda m: m.base_volume_raw, reverse=True)

for m in sorted_markets[:20]:
    pair = f"{m.base_symbol}/{m.quote_symbol}"
    price = f"{m.last_price:.6f}" if m.last_price else "N/A"
    vol = f"{m.base_volume_raw:>12,}"
    print(f"  {pair:<25} {price:>12} {vol}")

if len(markets) > 20:
    print(f"  ... and {len(markets) - 20} more markets")

print("=" * 60)

dex.close()
node.close()
