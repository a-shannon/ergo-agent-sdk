# Tutorial: Hello, Ergo!

This tutorial walks you through building a simple Ergo agent that can check balances, read oracle prices, and get swap quotes. Each step builds on the previous one.

**Time:** ~10 minutes  
**Prerequisites:** Python 3.10+, `pip install ergo-agent`

---

## Step 1: Connect to Ergo

```python
from ergo_agent import ErgoNode

node = ErgoNode()
height = node.get_height()
print(f"Ergo blockchain height: {height}")
```

```
Ergo blockchain height: 1325847
```

That's it — you're connected. The SDK uses the public Explorer API by default, no node setup required.

---

## Step 2: Check a Wallet Balance

```python
from ergo_agent import Wallet

wallet = Wallet.read_only("9f4QF8jQSBiHrgqrCDuS3L62MY6MaBFW5UeqNqfEi1mCfmPFxVo")
balance = node.get_balance(wallet.address)

print(f"Address: {wallet.address[:12]}...")
print(f"ERG:     {balance.erg:.4f}")
for token in balance.tokens:
    print(f"  {token.name or token.token_id[:8]}: {token.amount_display}")
```

```
Address: 9f4QF8jQSBiH...
ERG:     1.2345
  SigUSD: 50.00
```

!!! tip "Any address works"
    `Wallet.read_only()` accepts any valid Ergo address. You're just reading — no keys needed.

---

## Step 3: Get the ERG/USD Price

```python
from ergo_agent.defi import OracleReader

oracle = OracleReader(node)
price = oracle.get_erg_usd_price()
print(f"ERG/USD: ${price:.4f}")
```

```
ERG/USD: $0.3108
```

This reads the live price from the [Oracle Pool v2](https://github.com/ergoplatform/oracle-core) — the same data feed that SigmaUSD and other Ergo DeFi protocols use.

---

## Step 4: Get a DEX Quote

```python
from ergo_agent.defi import SpectrumDEX

dex = SpectrumDEX(node)
quote = dex.get_quote(token_in="ERG", token_out="SigUSD", amount_erg=10.0)

print(f"Swap 10 ERG → {quote.token_out_amount / 100:.2f} SigUSD")
print(f"Fee: {quote.fee_pct:.1f}%")
print(f"Price impact: {quote.price_impact_pct:.2f}%")
dex.close()
```

```
Swap 10 ERG → 3.05 SigUSD
Fee: 0.3%
Price impact: 0.01%
```

---

## Step 5: Wrap It All in a Toolkit

The `ErgoToolkit` bundles everything into a single interface that LLMs can call:

```python
from ergo_agent.tools import ErgoToolkit, SafetyConfig

toolkit = ErgoToolkit(
    node=node,
    wallet=wallet,
    safety=SafetyConfig(dry_run=True),  # dry_run = no real transactions
)

# Same operations, but as JSON-returning tool calls
print(toolkit.get_erg_price())
print(toolkit.get_swap_quote(token_in="ERG", token_out="SigUSD", amount_erg=1.0))
print(toolkit.get_safety_status())
```

Every method returns a JSON string that an LLM can parse and reason about.

---

## Step 6: Connect to an LLM

Here's a minimal OpenAI agent:

```python
import json
from openai import OpenAI

client = OpenAI()
tools = toolkit.to_openai_tools()

messages = [
    {"role": "system", "content": "You are an Ergo blockchain assistant."},
    {"role": "user", "content": "What is the current ERG price?"},
]

response = client.chat.completions.create(
    model="gpt-4o",
    tools=tools,
    messages=messages,
)

# Handle tool calls
for tool_call in response.choices[0].message.tool_calls or []:
    result = toolkit.execute_tool(tool_call.function.name, 
                                   json.loads(tool_call.function.arguments))
    print(f"Tool: {tool_call.function.name}")
    print(f"Result: {result}")
```

---

## Full Working Example

See [`examples/04_openai_agent.py`](https://github.com/ergoplatform/ergo-agent-sdk/blob/main/examples/04_openai_agent.py) for the complete, runnable version.

---

## What's Next?

- [**Architecture**](architecture.md) — understand *how* the SDK works under the hood
- [**API Reference**](api-reference.md) — look up specific methods
- [**Safety Layer**](getting-started.md#mode-2-node-wallet-transactions-enabled) — configure spending limits for production agents
