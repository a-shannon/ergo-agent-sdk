#!/usr/bin/env python3
"""
Example 10: Multi-tool agent (no LLM required).

Demonstrates using the ErgoToolkit as a standalone command-line tool
that can execute any of the 7 available tools by name.

Usage:
    python examples/10_cli_tool_runner.py get_erg_price
    python examples/10_cli_tool_runner.py get_wallet_balance
    python examples/10_cli_tool_runner.py get_swap_quote '{"token_in":"ERG","token_out":"SigUSD","amount_erg":5.0}'
    python examples/10_cli_tool_runner.py get_mempool_status
    python examples/10_cli_tool_runner.py get_safety_status
"""

import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from ergo_agent import ErgoNode, Wallet
from ergo_agent.tools import ErgoToolkit, SafetyConfig

# Setup
node = ErgoNode()
wallet = Wallet.read_only("9hRRQKSLZguckEaYXeAaSGJ5s5YySQNxH7LSy2R7R1J5Bqdx15C")
toolkit = ErgoToolkit(node=node, wallet=wallet, safety=SafetyConfig(dry_run=True))

# Parse command line
if len(sys.argv) < 2:
    print("Usage: python 10_cli_tool_runner.py <tool_name> [args_json]")
    print()
    print("Available tools:")
    for tool in toolkit.to_openai_tools():
        name = tool["function"]["name"]
        desc = tool["function"]["description"][:60]
        print(f"  {name:<25} {desc}")
    sys.exit(0)

tool_name = sys.argv[1]
tool_args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}

print(f"Tool:   {tool_name}")
print(f"Args:   {json.dumps(tool_args)}")
print("-" * 50)

result = toolkit.execute_tool(tool_name, tool_args)

# Pretty-print JSON result
try:
    parsed = json.loads(result)
    print(json.dumps(parsed, indent=2))
except (json.JSONDecodeError, TypeError):
    print(result)

node.close()
