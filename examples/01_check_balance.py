#!/usr/bin/env python3
"""
Example 01: Check a wallet balance.

Connects to the public Ergo API and reads the balance of any address.
No wallet keys or node required.

Usage:
    python examples/01_check_balance.py
    python examples/01_check_balance.py 9hRRQKSLZguckEaYXeAaSGJ5s5YySQNxH7LSy2R7R1J5Bqdx15C
"""

import sys

# Fix Windows encoding for Unicode token names
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from ergo_agent import ErgoNode, Wallet
from ergo_agent.tools import ErgoToolkit

# Use a well-known address or accept one from the command line
DEFAULT_ADDRESS = "9hRRQKSLZguckEaYXeAaSGJ5s5YySQNxH7LSy2R7R1J5Bqdx15C"
address = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS

# Connect
node = ErgoNode()
wallet = Wallet.read_only(address)
toolkit = ErgoToolkit(node=node, wallet=wallet)

# Get balance via toolkit (returns JSON string)
print("=== Toolkit JSON output ===")
print(toolkit.get_wallet_balance())

# Or use the node directly for a Balance object
print("\n=== Structured output ===")
balance = node.get_balance(address)
print(f"Address: {address[:16]}...")
print(f"ERG:     {balance.erg:.4f}")
if balance.tokens:
    print("Tokens:")
    for token in balance.tokens:
        name = token.name or token.token_id[:12] + "..."
        print(f"  {name}: {token.amount_display}")
else:
    print("Tokens:  (none)")

node.close()
