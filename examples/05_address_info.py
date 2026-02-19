#!/usr/bin/env python3
"""
Example 05: Address validation and info.

Demonstrates how to validate Ergo addresses, detect their type,
and derive ErgoTree representations.

Usage:
    python examples/05_address_info.py
    python examples/05_address_info.py 9hRRQKSLZgu...
"""

import sys

from ergo_agent.core.address import (
    address_to_ergo_tree,
    get_address_type,
    is_mainnet_address,
    is_p2pk_address,
    is_valid_address,
)

# Test addresses
addresses = [
    "9hRRQKSLZguckEaYXeAaSGJ5s5YySQNxH7LSy2R7R1J5Bqdx15C",  # real P2PK
    "invalid_address_123",
    "88dhgzEuTXaRaL3wq5RXXqRe8Bz1FKgpWasthisvalid",
]

if len(sys.argv) > 1:
    addresses = sys.argv[1:]

for addr in addresses:
    print(f"Address: {addr[:30]}{'...' if len(addr) > 30 else ''}")
    valid = is_valid_address(addr)
    print(f"  Valid:    {valid}")

    if valid:
        print(f"  Mainnet:  {is_mainnet_address(addr)}")
        print(f"  P2PK:     {is_p2pk_address(addr)}")
        print(f"  Type:     {get_address_type(addr)}")

        try:
            ergo_tree = address_to_ergo_tree(addr)
            print(f"  ErgoTree: {ergo_tree[:40]}...")
        except Exception as e:
            print(f"  ErgoTree: (error: {e})")
    print()
