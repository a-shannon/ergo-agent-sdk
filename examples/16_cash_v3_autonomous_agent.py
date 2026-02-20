import asyncio
import os
import argparse
from typing import Optional

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from ergo_agent.core.node import ErgoNode
from ergo_agent.core.wallet import Wallet
from ergo_agent.tools.toolkit import ErgoToolkit
from ergo_agent.tools.safety import SafetyConfig

# Suppress LangChain warnings
os.environ["LANGCHAIN_TRACING_V2"] = "false"


async def main():
    print("==============================================")
    print("  $CASH v3 -- AI Agent Ring Scanner  ")
    print("==============================================\n")


    # Initialize Ergo connection
    print("> Initializing SDK and connecting to ErgoNode...")
    node = ErgoNode()
    
    try:
        network_info = node.get_network_info()
        name = network_info.get('name', 'Ergo Network')
        print(f"> Connected to network: {name}")
    except Exception as e:
        print(f"> Failed to connect to node: {e}")
        return

    # Create a read-only wallet for the demonstration
    wallet = Wallet.read_only("9hRRQKSLZguckEaYXeAaSGJ5s5YySQNxH7LSy2R7R1J5Bqdx15C")

    # Safety limits for testing
    safety = SafetyConfig(
        max_erg_per_tx=150.0,
        max_erg_per_day=500.0,
        allowed_contracts=["spectrum", "sigmausd", "mock_pool_box_id_12345"],
        dry_run=True  # Important: don't actually sign/submit transactions
    )

    # Build the full toolkit integrating our new CashV3Client
    toolkit = ErgoToolkit(node, wallet, safety)
    tools = toolkit.to_langchain_tools()

    print(f"\n> Registered {len(tools)} Ergo tools including $CASH v3 Ring methods.")

    # For this offline demonstration, we will simulate the LLM's step-by-step reasoning
    # and tool execution using the injected tools
    prompt = "I have 100 $CASH. Scan for a pool with at least 8 depositors and make a private transfer to Bob at '9f4QF8AD1nQ3nJahQVkMj8hFSVVzVom77b52JU7EW71ZexG6N8v'."
    print(f"\n[USER PROMPT]: {prompt}\n")
    print("-------------------- AGENT THOUGHT PROCESS ---------------------")

    print("\n[AI]: I need to scan the blockchain for a $CASH v3 pool with a denomination of 100 that has an anonymity set of at least 8.")
    print("\n[TOOL CALLED: get_cash_pools] -> args: {'denomination': 100}")
    
    # Actually call the method from our toolkit!
    pool_data = toolkit.get_cash_pools(denomination=100)
    print(f"[TOOL RESULT] -> {pool_data}")
    
    # Parse the stubbed data
    pool_id = pool_data[0]["pool_id"]
    ring_size = pool_data[0]["current_ring_size"]

    print(f"\n[AI]: I found a suitable pool ({pool_id}) with a ring size of {ring_size}. I will now generate a stealth key and deposit 100 $CASH into the pool.")
    print(f"\n[TOOL CALLED: deposit_cash_to_pool] -> args: {{'pool_id': '{pool_id}', 'denomination': 100}}")
    
    # Actually call the method from our toolkit!
    deposit_res = toolkit.deposit_cash_to_pool(pool_id=pool_id, denomination=100)
    print(f"[TOOL RESULT] -> {deposit_res}")

    print(f"\n[AI]: The deposit transaction is built. The next block will mine it. I will now autonomously build the ring signature withdrawal transaction sending the $CASH to Bob's stealth address.")
    print(f"\n[TOOL CALLED: withdraw_cash_privately] -> args: {{'pool_id': '{pool_id}', 'recipient_address': '9f4QF8AD1nQ3nJahQVkMj8hFSVVzVom77b52JU7EW71ZexG6N8v', 'key_image': 'deadbeef'}}")
    
    # Actually call the method from our toolkit!
    withdraw_res = toolkit.withdraw_cash_privately(pool_id=pool_id, recipient_address="9f4QF8AD1nQ3nJahQVkMj8hFSVVzVom77b52JU7EW71ZexG6N8v", key_image="deadbeef")
    print(f"[TOOL RESULT] -> {withdraw_res}")

    print("\n[AI]: Both transactions have been successfully constructed and signed. Bob will receive his $CASH from an untraceable ring signature. Mission accomplished!")


if __name__ == "__main__":
    asyncio.run(main())
