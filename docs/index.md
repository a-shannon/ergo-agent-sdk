# 🤖⛓️ ergo-agent SDK

> **Give any LLM agent the power to interact with the Ergo blockchain.**

---

## What is ergo-agent?

**ergo-agent-sdk** is an open-source Python SDK that gives AI agents (Claude, GPT-4, LangChain, CrewAI) secure, autonomous access to the Ergo blockchain. Agents can read balances, fetch prices, execute DEX swaps, mint stablecoins via SigmaUSD, and bridge assets cross-chain via the Rosen Bridge. 

## Install

```bash
pip install ergo-agent-sdk
```

## 5-Line Quickstart

```python
from ergo_agent import ErgoNode, Wallet
from ergo_agent.tools import ErgoToolkit

node = ErgoNode()
wallet = Wallet.read_only("9f4QF8jQSBiHrgqrCDuS3L62MY6MaBFW5UeqNqfEi1mCfmPFxVo")
toolkit = ErgoToolkit(node=node, wallet=wallet)

print(toolkit.get_erg_price())    # → {"erg_usd": 0.31, "source": "oracle_pool_v2"}
print(toolkit.get_wallet_balance())  # → {"erg": "1.2345", "tokens": [...]}
```

That's it. No node required, no wallet keys, no setup. The public Explorer API is used by default.

## Key Features

| Feature | Description |
|---|---|
| 🔍 **Read-only queries** | Balance, price, mempool — no keys needed |
| 💱 **Spectrum DEX** | Swap quotes and orders on Spectrum Finance |
| 🏦 **SigmaUSD Stablecoins** | Mint and redeem SigUSD and SigRSV reserves |
| 🌉 **Rosen Bridge** | Cross-chain asset bridging out of Ergo |
| 🏛️ **DAO Treasuries** | Draft proposals and execute multi-sig actions |
| 📊 **Oracle prices** | Live ERG/USD from Oracle Pool v2 |
| 🔧 **LLM-ready** | OpenAI, Anthropic, and LangChain schemas |
| 🛡️ **Safety layer** | Per-tx limits, daily caps, contract whitelists |
| 🔑 **Wallet signing** | Sign transactions via Ergo node wallet API |

## Next Steps

- [**Getting Started**](getting-started.md) — detailed setup for all three modes (read-only, node wallet, LLM agent)
- [**Tutorial: Hello, Ergo!**](tutorial.md) — step-by-step walkthrough from zero to a working agent
- [**Architecture**](architecture.md) — how the SDK is structured and how Ergo's eUTXO model works
- [**API Reference**](api-reference.md) — complete reference for all classes and methods
