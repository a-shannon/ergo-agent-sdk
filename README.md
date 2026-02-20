# ergo-agent-sdk 🤖⛓️

> **Open-source Python SDK for AI agents on the Ergo blockchain.**

Give any LLM agent (Claude, GPT-4, LangChain, CrewAI...) the ability to read wallet balances, fetch live prices, swap tokens on Spectrum DEX — all autonomously, with built-in safety guardrails.

[![PyPI version](https://badge.fury.io/py/ergo-agent-sdk.svg)](https://badge.fury.io/py/ergo-agent-sdk)
[![Documentation Status](https://readthedocs.org/projects/ergo-agent-sdk/badge/?version=latest)](https://ergo-agent-sdk.readthedocs.io/en/latest/?badge=latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## Why?

Existing Ergo SDKs (ergpy, fleet-sdk, AppKit) are built for **human developers**. This SDK is built for **AI agents** — it speaks the language of function calling, returns structured JSON, and has a safety layer so the agent can't accidentally drain a wallet.

---

## Quickstart

```bash
pip install ergo-agent-sdk
```

### Read-only (no wallet needed)

```python
from ergo_agent import ErgoNode, Wallet
from ergo_agent.tools import ErgoToolkit, SafetyConfig

node = ErgoNode()
wallet = Wallet.read_only("9f...")  # any address to monitor
toolkit = ErgoToolkit(node=node, wallet=wallet)

# Check address balance
result = toolkit.get_wallet_balance()

# Get live ERG/USD price from Oracle Pool v2
price = toolkit.get_erg_price()
```

## Documentation

The complete SDK documentation, tutorial, and API reference are available at [ergo-agent-sdk.readthedocs.io](https://ergo-agent-sdk.readthedocs.io/).

## Next Steps
# Get a swap quote from Spectrum DEX
quote = toolkit.get_swap_quote(token_in="ERG", token_out="SigUSD", amount_erg=1.0)
```

### With a wallet (transactions enabled)

```python
from ergo_agent import ErgoNode, Wallet
from ergo_agent.tools import ErgoToolkit, SafetyConfig

node = ErgoNode(node_url="http://your-node:9053", api_key="your-key")
wallet = Wallet.from_node_wallet("9f...")

toolkit = ErgoToolkit(
    node=node,
    wallet=wallet,
    safety=SafetyConfig(
        max_erg_per_tx=5.0,
        max_erg_per_day=50.0,
        allowed_contracts=["spectrum"],
        rate_limit_per_hour=20,
    )
)

# Send ERG
toolkit.send_erg(to="9f...", amount_erg=1.5)

# Swap ERG for a token on Spectrum DEX
toolkit.swap_erg_for_token(token_out="SigUSD", amount_erg=1.0)
```

### Use with LLM frameworks

```python
# OpenAI function calling
tools = toolkit.to_openai_tools()

# Anthropic tool use
tools = toolkit.to_anthropic_tools()

# LangChain
lc_tools = toolkit.to_langchain_tools()
```

---

## Available Tools

| Tool | Description | Requires Wallet |
|---|---|---|
| `get_wallet_balance` | ERG + token balances | No |
| `get_erg_price` | Live ERG/USD from Oracle Pool v2 | No |
| `get_swap_quote` | Spectrum DEX swap quote | No |
| `get_mempool_status` | Pending transactions | No |
| `get_safety_status` | Current spending limits & usage | No |
| `send_funds` | Send ERG and/or native tokens to an address | Yes |
| `swap_erg_for_token` | Execute a swap on Spectrum DEX | Yes |
| `mint_sigusd` | Mint SigmaUSD stablecoins via AgeUSD Bank | Yes |
| `redeem_sigusd` | Redeem SigmaUSD to ERG | Yes |
| `mint_sigmrsv` | Mint ReserveCoins (Long ERG) | Yes |
| `redeem_sigmrsv` | Redeem ReserveCoins | Yes |
| `bridge_assets` | Bridge assets to other chains via Rosen Bridge | Yes |

---

## Architecture

```
ergo_agent/
├── core/        # ErgoNode client, Wallet, TransactionBuilder, Address utilities, Cryptography & Privacy primitives
├── defi/        # Oracle Pool v2, Spectrum DEX adapters
└── tools/       # LLM tool schemas (OpenAI / Anthropic / LangChain) + safety layer
```

---

## Safety Layer

Every state-changing action passes through `SafetyConfig` before execution:

```python
SafetyConfig(
    max_erg_per_tx=10.0,                  # hard cap per transaction
    max_erg_per_day=50.0,                 # daily rolling limit
    allowed_contracts=["spectrum"],        # contract whitelist
    rate_limit_per_hour=20,               # max 20 actions/hour
    dry_run=False,                        # set True for dry-run mode
)
```

---

## Network

By default the SDK connects to the **Ergo public API** (`https://api.ergoplatform.com`). For production use or transaction signing, point it at your own node:

```python
node = ErgoNode(node_url="http://your-node:9053", api_key="your-key")
```

---

## Contributing

This is an open-source project for the Ergo ecosystem. PRs welcome.

**Roadmap:**
- v0.1.0 — Core + Oracle + Spectrum + Tool schemas
- v0.2.x — Advanced Transaction Builder + Privacy primitives (Ring Signatures)
- v0.3.x — SigmaUSD + Rosen Bridge adapters + Treasury contracts *(current)*

---

## License

MIT
