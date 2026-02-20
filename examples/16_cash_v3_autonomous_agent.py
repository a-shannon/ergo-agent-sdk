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

    if "OPENAI_API_KEY" not in os.environ:
        print("ERROR: OPENAI_API_KEY environment variable is required.")
        return

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
        dry_run=True  # Important: don't actually sign/submit transactions
    )

    # Build the full toolkit integrating our new CashV3Client
    toolkit = ErgoToolkit(node, wallet, safety)
    tools = toolkit.to_langchain_tools()

    print(f"\n> Registered {len(tools)} Ergo tools including $CASH v3 Ring methods.")

    # Select the model
    llm = ChatOpenAI(model="gpt-4o")

    # The magic system prompt guiding the Ring Agent
    system_prompt = """
    You are an autonomous privacy financial agent on the Ergo Blockchain.
    You have access to a suite of Ergo tools, including the ability to interact with $CASH v3 privacy pools.
    
    The user wants to make a private transfer using a $CASH pool.
    1. Scan the active pools for the requested denomination.
    2. Pick the pool with the mathematically highest anonymity set (current_ring_size). The ring size MUST be at least 8.
    3. If a suitable pool is found, execute `deposit_cash_to_pool`.
    4. Then immediately execute `withdraw_cash_privately` to send the funds to the target address privately. Use the mock key image 'deadbeef'.
    5. Always report back clearly what you are doing.
    """

    agent = create_react_agent(llm, tools, state_modifier=system_prompt)

    prompt = "I have 100 $CASH. Scan for a pool with at least 8 depositors and make a private transfer to Bob at '9f4QF8AD1nQ3nJahQVkMj8hFSVVzVom77b52JU7EW71ZexG6N8v'."
    print(f"\n[USER PROMPT]: {prompt}\n")
    print("-------------------- AGENT THOUGHT PROCESS ---------------------")

    # Execute the LangGraph loop
    state = await agent.ainvoke(
        {"messages": [HumanMessage(content=prompt)]}
    )

    # Print the resulting interactions back for the user to witness
    for block in state["messages"]:
        if block.type == "ai" and block.content:
             print(f"\n[AI]: {block.content}")
        elif block.type == "tool":
             print(f"\n[TOOL CALLED] -> result: {block.content}")


if __name__ == "__main__":
    asyncio.run(main())
