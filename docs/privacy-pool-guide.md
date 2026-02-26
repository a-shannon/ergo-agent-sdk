# Privacy Pool Protocol — Usage Guide

This guide covers the complete privacy pool workflow: depositing tokens, withdrawing anonymously, and monitoring pool health.

## Prerequisites

```bash
pip install ergo-agent-sdk httpx
```

```python
from ergo_agent.core.node import ErgoNode
from ergo_agent.core.wallet import Wallet
from ergo_agent.defi.privacy_pool import PrivacyPoolClient
```

## Quick Start

```python
node = ErgoNode(
    node_url="http://127.0.0.1:9052",
    explorer_url="https://api-testnet.ergoplatform.com",
    api_key="your_api_key",
)
wallet = Wallet.from_node_wallet("your_address")
pool = PrivacyPoolClient(node=node, wallet=wallet)
```

## 1. Pool Discovery

### List Active Pools

```python
pools = pool.get_active_pools(denomination=100)
for p in pools:
    print(f"Pool: {p['pool_id'][:16]}...")
    print(f"  Ring: {p['depositors']}/{p['max_depositors']}")
    print(f"  Slots: {p['slots_remaining']}")
    print(f"  Tokens: {p['token_balance']}")
```

### Auto-Select Best Pool

```python
best = pool.select_best_pool(denomination=100)
if best:
    print(f"Best pool: {best['pool_id'][:16]}... (ring={best['depositors']})")
```

## 2. Deposit

```python
from ergo_agent.core.privacy import generate_fresh_secret

# Generate a one-time secret + public key pair
secret_hex, stealth_key = generate_fresh_secret()

pool_id = best["pool_id"]
builder = pool.build_deposit_tx(pool_id, stealth_key, denomination=100)
tx = builder.build()
signed = wallet.sign_transaction(tx, node)
tx_id = node.submit_transaction(signed)
print(f"Deposit TX: {tx_id}")
```

!!! danger "Save Your Secret Key"
    You **must** save `secret_hex` securely — it is required for withdrawal.
    Losing it means losing access to your deposited tokens permanently.

!!! warning "Security Validations"
    The SDK automatically blocks:

    - **groupGenerator** as stealth key (trivially provable slot)
    - **H constant** as stealth key (compromises DH tuple proof)
    - **Duplicate keys** already in the pool's ring
    - **Full pools** (capacity pre-check)

## 3. Withdrawal

```python
# Use the secret_hex saved during deposit
recipient = "9h..."  # Fresh Ergo address (never used before)

builder = pool.build_withdrawal_tx(pool_id, recipient, secret_hex)
tx = builder.build()
signed = wallet.sign_transaction(tx, node)
tx_id = node.submit_transaction(signed)
```

The SDK handles everything internally:

1. **Computes the key image** (nullifier) from your secret: `M = secret × H`
2. **Generates the AvlTree insert proof** via `ergo_avltree`
3. **Serializes context extension** variables with correct Sigma types
4. **Builds the ring signature** proof (handled by the node's prover at signing time)

!!! danger "Privacy Best Practices"
    - **Never reuse** the recipient withdrawal address
    - **Wait at least 2 blocks** between deposit and withdrawal
    - **Use a fresh IP address** or Tor when withdrawing
    - Check pool health before withdrawing — low ring sizes reduce anonymity

## 4. Pool Health Analytics

```python
health = pool.evaluate_pool_health(pool_id)
print(f"Privacy Score: {health['privacy_score']}")
print(f"Effective Anonymity: {health['effective_anonymity']}")
print(f"Risk Flags: {health['risk_flags']}")
```

**Privacy Score Levels:**

| Score | Meaning |
|-------|---------| 
| EXCELLENT | 8+ unique depositors, no risk flags |
| GOOD | 6-7 unique depositors |
| FAIR | 4-5 unique depositors |
| POOR | 2-3 unique depositors |
| CRITICAL | <2 unique depositors or multiple risk flags |

## 5. Toolkit (Agent-Facing API)

If you're using the `ErgoToolkit` for AI agent integration:

```python
from ergo_agent.tools.toolkit import ErgoToolkit

toolkit = ErgoToolkit(node=node, wallet=wallet)

# Deposit — auto-generates and returns the secret key
result = toolkit.deposit_to_privacy_pool(pool_id="...", denomination=100)
secret_key = result["secret_key"]  # Save this!

# Withdraw — pass the secret key, everything else is computed internally
result = toolkit.withdraw_from_privacy_pool(
    pool_id="...",
    recipient_address="9h...",
    secret_key=secret_key,
)
```

## 6. API Bridge (Relayer)

For frontend integration, use the FastAPI relayer:

```bash
cd ergo
uvicorn api.server:app --port 8000
```

**Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/pools` | List active pools |
| `GET` | `/api/pools/{id}/health` | Pool health report |
| `POST` | `/api/deposit` | Submit deposit TX |
| `POST` | `/api/withdraw` | Submit withdrawal TX |
| `GET` | `/api/health` | API health check |
