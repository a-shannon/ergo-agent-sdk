#!/usr/bin/env python3
"""
Example 04: Minimal OpenAI function-calling agent.

This creates a simple chat agent that can answer questions about the Ergo
blockchain by calling the SDK's tools via OpenAI function calling.

Requirements:
    pip install ergo-agent[openai]
    export OPENAI_API_KEY=sk-...

Usage:
    python examples/04_openai_agent.py "What is the current ERG price?"
    python examples/04_openai_agent.py "Check the balance of 9f4QF8jQ..."
"""

import json
import sys

try:
    from openai import OpenAI
except ImportError:
    print("Install OpenAI: pip install ergo-agent[openai]")
    sys.exit(1)

from ergo_agent import ErgoNode, Wallet
from ergo_agent.tools import ErgoToolkit, SafetyConfig

# Setup
node = ErgoNode()
wallet = Wallet.read_only("9hRRQKSLZguckEaYXeAaSGJ5s5YySQNxH7LSy2R7R1J5Bqdx15C")
toolkit = ErgoToolkit(
    node=node,
    wallet=wallet,
    safety=SafetyConfig(dry_run=True),  # safety: never send real transactions
)

# Get the user question
question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "What is the current ERG price?"

print(f"Question: {question}")
print()

# Build messages
client = OpenAI()
tools = toolkit.to_openai_tools()
messages = [
    {
        "role": "system",
        "content": (
            "You are an Ergo blockchain assistant. "
            "Use the provided tools to answer questions about ERG balances, "
            "prices, and DeFi operations. Be concise and helpful."
        ),
    },
    {"role": "user", "content": question},
]

# First call — LLM decides which tools to call
response = client.chat.completions.create(
    model="gpt-4o-mini",
    tools=tools,
    messages=messages,
)

choice = response.choices[0]

# Handle tool calls
if choice.message.tool_calls:
    messages.append(choice.message)

    for tool_call in choice.message.tool_calls:
        fn_name = tool_call.function.name
        fn_args = json.loads(tool_call.function.arguments)
        print(f"🔧 Calling: {fn_name}({fn_args})")

        result = toolkit.execute_tool(fn_name, fn_args)
        print(f"   Result: {result}")
        print()

        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            }
        )

    # Second call — LLM synthesizes the answer
    final = client.chat.completions.create(
        model="gpt-4o-mini",
        tools=tools,
        messages=messages,
    )
    print(f"🤖 {final.choices[0].message.content}")
else:
    # No tool calls needed
    print(f"🤖 {choice.message.content}")

node.close()
