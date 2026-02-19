#!/usr/bin/env python3
"""
Example 07: Mempool monitor.

Checks the Ergo mempool for unconfirmed transactions for a given
address and displays block height and network info.

Usage:
    python examples/07_mempool_monitor.py
    python examples/07_mempool_monitor.py 9hRRQKSLZgu...
"""

import sys

from ergo_agent import ErgoNode

ADDRESS = sys.argv[1] if len(sys.argv) > 1 else "9hRRQKSLZguckEaYXeAaSGJ5s5YySQNxH7LSy2R7R1J5Bqdx15C"

node = ErgoNode()

# Current block height
height = node.get_height()

# Network info
net_info = node.get_network_info()

# Mempool for address
mempool = node.get_mempool_transactions(ADDRESS)

print("=" * 55)
print("  ERGO NETWORK & MEMPOOL MONITOR")
print("=" * 55)
print(f"  Block height:    {height}")
print(f"  Network:         {net_info.get('network_type', 'mainnet')}")
print(f"  Difficulty:      {net_info.get('difficulty', 'N/A')}")
print(f"  Hash rate:       {net_info.get('hash_rate', 'N/A')}")
print("-" * 55)
print(f"  Address: {ADDRESS[:16]}...{ADDRESS[-6:]}")
print(f"  Pending txs:     {len(mempool)}")

if mempool:
    for i, tx in enumerate(mempool[:10]):
        tx_id = tx.get("id", "unknown")
        outputs = tx.get("outputs", [])
        tx_value = sum(o.get("value", 0) for o in outputs)
        print(f"  [{i+1}] {tx_id[:20]}... | {tx_value/1e9:.4f} ERG")
    if len(mempool) > 10:
        print(f"  ... and {len(mempool) - 10} more")
else:
    print("  No pending transactions for this address")

print("=" * 55)

node.close()
