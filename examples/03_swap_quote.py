#!/usr/bin/env python3
"""
Example 03: Get a swap quote from Spectrum DEX.

Fetches a live swap quote for ERG → SigUSD, showing expected output,
fees, and price impact.

Usage:
    python examples/03_swap_quote.py
    python examples/03_swap_quote.py 5.0     # swap 5 ERG
    python examples/03_swap_quote.py 5.0 SigRSV  # swap 5 ERG for SigRSV
"""

import sys

from ergo_agent import ErgoNode
from ergo_agent.defi import SpectrumDEX

amount_erg = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
token_out = sys.argv[2] if len(sys.argv) > 2 else "SigUSD"

node = ErgoNode()
dex = SpectrumDEX(node)

print(f"Getting quote: {amount_erg} ERG -> {token_out}")
print()

quote = dex.get_quote(token_in="ERG", token_out=token_out, amount_erg=amount_erg)

if quote is None:
    print(f"No market found for ERG/{token_out}")
else:
    # SigUSD has 2 decimals, most tokens have varying decimals
    print(f"=== Swap Quote ===")
    print(f"Input:        {amount_erg} ERG")
    print(f"Output:       {quote.token_out_amount} (raw units)")
    print(f"Pool:         {quote.pool_id[:16]}...")
    print(f"Fee:          {quote.fee_pct:.1f}%")
    print(f"Price impact: {quote.price_impact_pct:.2f}%")

dex.close()
node.close()
