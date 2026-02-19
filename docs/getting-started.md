# Getting Started

This guide gets you from zero to your first Ergo query in under 2 minutes.

---

## Installation

```bash
pip install ergo-agent
```

For LLM framework integration, install the extras you need:

=== "OpenAI"

    ```bash
    pip install ergo-agent[openai]
    ```

=== "Anthropic"

    ```bash
    pip install ergo-agent[anthropic]
    ```

=== "LangChain"

    ```bash
    pip install ergo-agent[langchain]
    ```

=== "All"

    ```bash
    pip install ergo-agent[all]
    ```

---

## Mode 1: Read-Only (no wallet)

Perfect for price bots, portfolio trackers, and exploration.

```python
from ergo_agent import ErgoNode, Wallet
from ergo_agent.tools import ErgoToolkit

node = ErgoNode()  # uses public API — no node required
wallet = Wallet.read_only("9f4QF8jQSBiHrgqrCDuS3L62MY6MaBFW5UeqNqfEi1mCfmPFxVo")
toolkit = ErgoToolkit(node=node, wallet=wallet)

# Check balance
balance = toolkit.get_wallet_balance()
print(balance)

# Get live ERG/USD price
price = toolkit.get_erg_price()
print(price)
```

!!! note "No API key needed"
    The SDK uses the public `api.ergoplatform.com` by default. Rate limits are generous for development use.

---

## Mode 2: Node Wallet (transactions enabled)

For sending ERG, swapping tokens, and signing transactions.

```python
from ergo_agent import ErgoNode, Wallet
from ergo_agent.tools import ErgoToolkit, SafetyConfig

# Connect to your own Ergo node
node = ErgoNode(node_url="http://localhost:9053", api_key="your-api-key")
wallet = Wallet.from_node_wallet("9f...")

toolkit = ErgoToolkit(
    node=node,
    wallet=wallet,
    safety=SafetyConfig(
        max_erg_per_tx=5.0,       # hard cap per transaction
        max_erg_per_day=50.0,     # rolling 24h limit
        rate_limit_per_hour=20,   # max 20 actions/hour
    ),
)

# Send ERG (passes through safety checks)
result = toolkit.send_erg(to="9f...", amount_erg=1.5)
```

!!! warning "Node required"
    Transaction signing requires connecting to an Ergo node with the wallet API unlocked. See the [Ergo node setup guide](https://docs.ergoplatform.com/node/install/) for instructions.

---

## Mode 3: LLM Agent Integration

Connect any LLM to the Ergo blockchain with tool/function calling.

=== "OpenAI"

    ```python
    from ergo_agent import ErgoNode, Wallet
    from ergo_agent.tools import ErgoToolkit

    node = ErgoNode()
    wallet = Wallet.read_only("9f...")
    toolkit = ErgoToolkit(node=node, wallet=wallet)

    # Generate OpenAI function-calling tool definitions
    tools = toolkit.to_openai_tools()
    # Pass `tools` to your OpenAI chat completion call
    ```

=== "Anthropic"

    ```python
    tools = toolkit.to_anthropic_tools()
    # Pass `tools` to your Anthropic messages call
    ```

=== "LangChain"

    ```python
    lc_tools = toolkit.to_langchain_tools()
    # Use with LangChain's AgentExecutor or create_tool_calling_agent
    ```

When the LLM calls a tool, execute it:

```python
result = toolkit.execute_tool("get_erg_price", {})
# Returns JSON string: {"erg_usd": 0.31, "source": "oracle_pool_v2"}
```

---

## What's Next?

- [**Tutorial: Hello, Ergo!**](tutorial.md) — build a complete price-checking agent step by step
- [**Architecture**](architecture.md) — understand the SDK layers and Ergo's eUTXO model
- [**API Reference**](api-reference.md) — look up any class or method
