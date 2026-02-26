# Architecture

## SDK Layers

The SDK is organized into three layers. Each layer only depends on the one below it.

```mermaid
graph TB
    A["🤖 tools/<br/>ErgoToolkit, SafetyConfig<br/>OpenAI / Anthropic / LangChain schemas"] --> B
    B["💱 defi/<br/>OracleReader, SpectrumDEX, SigmaUSD<br/>RosenBridge, PrivacyPoolClient, Treasury"] --> C
    C["⛓️ core/<br/>ErgoNode, Wallet, TransactionBuilder<br/>Address, Privacy, Models"]
    
    style A fill:#7c3aed,color:#fff
    style B fill:#f59e0b,color:#000
    style C fill:#10b981,color:#fff
```

### Core Layer (`ergo_agent.core`)

The foundation. Handles all direct blockchain interaction.

| Class | Purpose |
|---|---|
| `ErgoNode` | REST client for the Explorer API and node API |
| `Wallet` | Address management and transaction signing |
| `TransactionBuilder` | UTXO selection, fee calculation, change handling, explicit inputs + context extensions |
| `address` | Base58 validation, ErgoTree derivation, checksum verification |
| `privacy` | Privacy pool protocol: PrivacyPoolV6 contract, key image computation, AvlTree proofs, ring signature support |
| `models` | Data classes: `Box`, `Balance`, `Token`, `Transaction`, `SwapQuote` |

### DeFi Layer (`ergo_agent.defi`)

Protocol-specific adapters built on top of core.

| Class | Purpose |
|---|---|
| `OracleReader` | Reads ERG/USD price from Oracle Pool v2 |
| `SpectrumDEX` | Markets, swap quotes, and order construction for Spectrum Finance |
| `SigmaUSD` | Mint and redeem SigUSD/SigRSV via the AgeUSD bank contract |
| `RosenBridge` | Cross-chain asset bridging out of Ergo |
| `PrivacyPoolClient` | Ring-signature privacy pools: deposit, withdraw, health monitoring |
| `ErgoTreasury` | DAO proposal creation, voting, and execution |

### Tools Layer (`ergo_agent.tools`)

The AI-facing interface. Wraps everything into LLM-compatible tool calls.

| Class | Purpose |
|---|---|
| `ErgoToolkit` | Main entry point — 15 tools, JSON output, `execute_tool()` dispatch |
| `SafetyConfig` | Per-tx limits, daily caps, rate limiting, contract whitelist, privacy timing guards |
| `to_openai_tools()` | OpenAI function-calling schema |
| `to_anthropic_tools()` | Anthropic tool use schema |
| `to_langchain_tools()` | LangChain `@tool` wrappers |

---

## How Ergo's eUTXO Model Works

!!! info "For developers coming from EVM"
    If you're used to Ethereum, Ergo's model is fundamentally different. This section explains the key concepts.

### Boxes, Not Accounts

Ergo doesn't have accounts with balances. Instead, it uses **boxes** (enhanced UTXOs):

```mermaid
graph LR
    subgraph "Transaction"
        direction LR
        I1["📦 Input Box<br/>5 ERG"] --> TX["🔄 Tx"]
        TX --> O1["📦 Output Box 1<br/>3 ERG → recipient"]
        TX --> O2["📦 Output Box 2<br/>1.999 ERG → change"]
        TX --> O3["📦 Output Box 3<br/>0.001 ERG → fee"]
    end
```

- **Input boxes** are consumed (destroyed) by the transaction
- **Output boxes** are created by the transaction
- The sum of inputs must equal the sum of outputs (conservation)
- Your "balance" is the sum of all unspent boxes at your address

### What Makes Ergo Boxes Special

Unlike Bitcoin UTXOs, Ergo boxes have:

| Feature | Description |
|---|---|
| **ErgoTree** | A script (compiled ErgoScript) that defines spending conditions |
| **Registers R0–R9** | Typed data storage — R0 is value, R1 is script, R4–R9 are custom |
| **Tokens** | Each box can hold multiple tokens alongside ERG |
| **Creation height** | Block height when the box was created |

This is why the SDK has a `TransactionBuilder` — constructing a transaction means selecting input boxes, creating output boxes, and handling change.

### Advanced Cryptography: Privacy Pool Ring Signatures

Because Ergo uses Sigma Protocols natively, the SDK's `TransactionBuilder` and `privacy` modules support advanced zero-knowledge proofs like **Ring Signatures** out of the box:

1. **Deposit**: A user generates a fresh secret+public key pair, adds their public key to a `PoolBox` (in register `R4`) and deposits tokens.
2. **Withdrawal**: The SDK computes the **key image** (nullifier) from the depositor's secret (`M = secret × H`), generates an **AvlTree insert proof** for the nullifier set (`R5`), and constructs a ring signature (`proveDlog` + `proveDHTuple` + `atLeast`) proving membership without revealing identity.
3. **Double-spend prevention**: The key image is inserted into an authenticated AVL+ tree (`R5`). The contract verifies the proof and rejects duplicate key images.

The unified **PrivacyPoolV6** contract handles deposits, withdrawals, and renewal paths via lazy `if/else` branching on the token differential. The SDK abstracts all cryptographic complexity via `compute_key_image()`, `generate_avl_insert_proof()`, and `serialize_context_extension()`.

### How the SDK Handles This

```mermaid
sequenceDiagram
    participant Agent as LLM Agent
    participant Toolkit as ErgoToolkit
    participant Builder as TransactionBuilder
    participant Node as ErgoNode

    Agent->>Toolkit: send_erg(to="9f...", amount=1.5)
    Toolkit->>Toolkit: SafetyConfig.validate()
    Toolkit->>Node: get_unspent_boxes(address)
    Node-->>Toolkit: [Box, Box, Box, ...]
    Toolkit->>Builder: send(to, amount_erg)
    Builder->>Builder: Select inputs (greedy)
    Builder->>Builder: Create output + change + fee
    Builder-->>Toolkit: unsigned_tx dict
    Toolkit->>Node: submit_transaction(tx)
    Node-->>Agent: tx_id
```

The agent never sees UTXOs, box IDs, or ErgoTrees. It just calls `send_erg()` and gets back a transaction ID.

---

## Safety Architecture

```mermaid
graph LR
    A["Agent calls<br/>send_erg()"] --> B{"SafetyConfig"}
    B -->|"✅ passes"| C["Execute"]
    B -->|"❌ per-tx limit"| D["SafetyViolation"]
    B -->|"❌ daily limit"| D
    B -->|"❌ rate limit"| D
    B -->|"❌ contract not whitelisted"| D
```

Every state-changing action passes through `SafetyConfig` before execution. The safety layer is **not optional** — even if you don't configure it, sensible defaults apply.

| Guard | Default | Purpose |
|---|---|---|
| `max_erg_per_tx` | 100 ERG | Prevent single catastrophic transaction |
| `max_erg_per_day` | 1000 ERG | Rolling 24h spending cap |
| `rate_limit_per_hour` | 60 | Prevent runaway loops |
| `allowed_contracts` | `[]` (any) | Whitelist protocols the agent can interact with |
| `dry_run` | `False` | Log but don't execute (for testing) |
| `min_withdrawal_delay_blocks` | 100 | Recommended blocks between deposit and withdrawal |
| `min_pool_ring_size` | 4 | Minimum ring size for withdrawal safety |
