#!/usr/bin/env python3
"""
Example 06: Portfolio tracker.

Monitors a wallet address and displays a formatted portfolio with
ERG value in USD, token holdings, and total estimated value.

Usage:
    python examples/06_portfolio_tracker.py
    python examples/06_portfolio_tracker.py 9hRRQKSLZgu...
"""

import sys

from ergo_agent import ErgoNode
from ergo_agent.defi import OracleReader, SpectrumDEX

ADDRESS = sys.argv[1] if len(sys.argv) > 1 else "9hRRQKSLZguckEaYXeAaSGJ5s5YySQNxH7LSy2R7R1J5Bqdx15C"

node = ErgoNode(timeout=20.0)

# Get balance
balance = node.get_balance(ADDRESS)

# Get ERG/USD price
oracle = OracleReader(node)
erg_usd = oracle.get_erg_usd_price()

# Print portfolio
print("=" * 50)
print(f"  ERGO PORTFOLIO TRACKER")
print("=" * 50)
print(f"  Address: {ADDRESS[:16]}...{ADDRESS[-6:]}")
print(f"  ERG/USD: ${erg_usd:.4f}")
print("-" * 50)

erg_value_usd = balance.erg * erg_usd
print(f"  ERG:     {balance.erg:>12.4f}  (${erg_value_usd:.2f})")

if balance.tokens:
    print("-" * 50)
    print("  TOKENS:")
    for token in balance.tokens:
        name = token.name or token.token_id[:12] + "..."
        display = token.amount_display
        # Pad name for alignment
        print(f"    {name:<20} {display:>12}")

print("-" * 50)
print(f"  ERG Value:  ${erg_value_usd:.2f} USD")
print("=" * 50)

node.close()
