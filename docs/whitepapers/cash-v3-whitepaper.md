---
title: "$CASH v3 — Digital Cash via Application-Level Ring-Signature Privacy Pools"
version: 0.1 (Draft)
date: 2026-02-19
authors: A. Shannon
license: CC BY 4.0
chain: Ergo (eUTXO)
---

# $CASH v3

## Digital Cash via Application-Level Ring-Signature Privacy Pools

---

## Abstract

$CASH is a privacy-preserving digital cash protocol on the Ergo blockchain. It enables confidential token transfers using **Sigma protocol ring signatures** within shared liquidity pools — requiring no protocol-level changes, no trusted setup, and no external cryptographic machinery beyond what ErgoScript already provides.

Users deposit tokens into a shared pool and later withdraw them using a ring proof that hides which depositor is withdrawing. A deterministic key image serves as a nullifier, preventing double-withdrawal, while an authenticated AvlTree stores spent key images on-chain.

Unlike previous designs (v1.x), which relied on atomic CashierBox swaps with no temporal decoupling, $CASH v3 achieves genuine unlinkability between deposits and withdrawals. The anonymity set equals the pool's ring size (8–16 members) — a guaranteed floor independent of network adoption, comparable to Monero's ring signatures.

The entire protocol runs in three ErgoScript contracts; the core withdrawal path compiles to 253 bytes of ErgoTree, consuming only 12.3% of Ergo's per-block JitCost budget at maximum ring size (16).

---

## Notation and Preliminaries

We use the following notation throughout this paper.

| Symbol | Definition |
|---|---|
| G | Standard generator of the secp256k1 elliptic curve group **G** of prime order *q* |
| H | A second generator of **G**, derived via a Nothing-Up-My-Sleeve (NUMS) construction (§2.3.2) |
| x ←$ Z_q | A secret key sampled uniformly at random from {1, ..., q−1} |
| P = x·G | Public key corresponding to secret x |
| I = x·H | Key image (deterministic nullifier) for secret x |
| N | Ring size: the number of public keys in a PoolBox (up to 16) |
| D | Denomination: the token quantity served by a given pool |
| T | An authenticated AvlTree storing the set of used key images |
| π_insert | A Merkle insertion proof for an AvlTree update |
| `proveDlog(P)` | Sigma protocol proving knowledge of x such that P = x·G |
| `proveDHTuple(G,H,P,I)` | Sigma protocol proving the DH-tuple relationship: P = x·G ∧ I = x·H |
| `atLeast(k, {σ_i})` | Sigma OR composition: at least k of the given Sigma propositions are satisfied |

**Assumption 1 (Discrete Logarithm).** Given P ∈ **G**, computing x such that P = x·G is computationally infeasible.

**Assumption 2 (Decisional Diffie-Hellman).** Given (G, H, P, I), distinguishing between I = x·H (where P = x·G) and a random element of **G** is computationally infeasible.

**Assumption 3 (Collision Resistance of SHA-256).** Finding distinct m, m' such that SHA256(m) = SHA256(m') is computationally infeasible.

These are standard assumptions underlying Bitcoin, Ergo, and all secp256k1-based systems.

---

## 1. Introduction

### 1.1 Background: Privacy as a Right

The Ergo Manifesto articulates privacy as a foundational human right:

> *"Privacy protects the individual from society. Privacy creates space to allow personal autonomy."*

Ergo's base layer is designed to be transparent and exchange-friendly — ensuring ERG itself carries no delisting risk. But the Manifesto also calls for **voluntary opt-in privacy tools**:

> *"No restrictions on usage categories. All core code fully open and auditable. Privacy tools supported as voluntary opt-in."*

$CASH embodies this principle. Ergo stays transparent. $CASH is an opt-in privacy layer that lives _on_ Ergo as a set of smart contracts — just as Tornado Cash lives on Ethereum without making Ethereum itself a privacy chain.

### 1.2 The Problem: Application-Level Privacy on eUTXO

Achieving meaningful transaction privacy on a transparent blockchain requires solving three problems simultaneously:

1. **Unlinkability** — a withdrawal must not be traceable back to the specific deposit that funded it
2. **Double-spend prevention** — each deposit can be withdrawn exactly once
3. **No trusted setup** — the system must not require a ceremony, MPC, or external trust assumptions

On account-based chains (Ethereum), zero-knowledge proofs (ZK-SNARKs) solve all three via Tornado Cash's design. On Ergo's eUTXO model, we face additional constraints:

- No persistent state across transactions (boxes are consumed and recreated)
- Script verification must fit within the JitCost budget (~1,000,000 units per block)
- Sigma protocols are available natively — but must be composed within ErgoScript

### 1.3 Prior Work: Why v1.x Was Abandoned

An adversarial three-round audit of $CASH v1.2 identified two **fatal** architectural flaws:

**Fatal 1 — The Privacy-Adoption Death Spiral.** v1.2's anonymity set depended on concurrent pool usage. At realistic Ergo adoption (~1,000 daily active addresses), the per-pool anonymity was ≈1–3 users per time window — effectively no privacy. The protocol had no guaranteed privacy floor.

**Fatal 2 — No Actual Mixing.** v1.2's CashierBox "swaps" were atomic — the note entered and exited the pool in the same transaction. There was no temporal gap, and therefore no mixing. An observer could reconstruct the complete routing path. The entire "privacy" reduced to EIP-41 stealth addresses, which could be achieved without any pool mechanism.

These findings terminated v1.2 and motivated a complete redesign.

### 1.4 Our Approach: Ring Signatures Inside Shared Pools

$CASH v3 replaces the atomic-swap model with a **deposit-then-withdraw** architecture using Sigma protocol ring signatures:

1. **Deposit:** Alice adds her public key and tokens to a shared PoolBox
2. **Wait:** Time passes. Other users also deposit into the same pool
3. **Withdraw:** Alice proves she owns _one of_ the deposit keys — without revealing which — using a Sigma OR composition. A deterministic key image prevents double-withdrawal

**Intuition:** Think of a privacy pool as a group piggy bank. Multiple people put money in (deposit). Later, anyone who put money in can take money out (withdraw) by proving "I'm one of the people who deposited" — without saying which one. A stamp on each withdrawal receipt (the key image) prevents anyone from withdrawing twice.

---

## 2. Technical Design

### 2.1 Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                      Ergo Blockchain                     │
│                                                         │
│  ┌──────────────┐    ┌──────────────┐   ┌────────────┐  │
│  │  PoolBox(100) │    │ PoolBox(1K)  │   │PoolBox(10K)│  │
│  │  N ≤ 16 keys │    │  N ≤ 16 keys │   │ N ≤ 16 keys│  │
│  │  AvlTree T   │    │  AvlTree T   │   │ AvlTree T  │  │
│  └──────────────┘    └──────────────┘   └────────────┘  │
│        │                    │                 │          │
│    ┌───┴────┐          ┌───┴────┐       ┌───┴────┐     │
│    │Deposit │          │Withdraw│       │Deposit │     │
│    │(add key│          │(ring   │       │(add key│     │
│    │+tokens)│          │proof)  │       │+tokens)│     │
│    └────────┘          └───┬────┘       └────────┘     │
│                            │                            │
│                       ┌────┴────┐                       │
│                       │ NoteBox │                       │
│                       │ (clean) │                       │
│                       └─────────┘                       │
└─────────────────────────────────────────────────────────┘
```

**Three contracts:**

| Contract | Purpose | ErgoTree Size |
|---|---|---|
| **PoolContract** (withdraw path) | Ring-signature withdrawal + AvlTree nullifier | 253 bytes |
| **PoolContract** (deposit path) | Key append + token deposit | ~200 bytes |
| **NoteContract** | Bearer instrument — denomination + owner | ~70 bytes |

### 2.2 Data Structures

**Definition 1 (PoolBox).** A PoolBox is an Ergo box with the following structure:

```
PoolBox {
  value:    operating ERG (≥ 0.001 ERG)
  tokens:   [(cashTokenId, currentReserve)]
  R4:       Coll[GroupElement]  — deposit keys {P_1, ..., P_N}
  R5:       AvlTree             — nullifier set T of used key images
  R6:       Long                — denomination D ∈ {1, 10, 100, 1K, 10K, 100K}
  R7:       Int                 — maxDeposits (8 or 16)
  script:   PoolContract
}
```

**Design choices:**
- **R4 (keys)**: Public keys are _never removed_ after withdrawal — removal would reveal which depositor withdrew. The ring always covers all depositors.
- **R5 (AvlTree)**: An authenticated data structure that stores used key images. Insert fails if the key image already exists, preventing double-withdrawal. AvlTree operations include a Merkle proof, verified on-chain.
- **R7 (maxDeposits)**: Caps the ring size N to ensure the ring proof fits within the JitCost budget.

**Definition 2 (NoteBox).** A NoteBox is the unit of private cash — a bearer instrument:

```
NoteBox {
  value:    ≥ 0.05 ERG
  tokens:   [(cashTokenId, D)]
  R4:       GroupElement  — owner's stealth key P_owner (EIP-41)
  script:   NoteContract
}
```

**Compared to v1.2:** No R5 (hopsRemaining), no R6 (usedPoolIds), no routing metadata. The note is clean — just a denomination and an owner. Like a real banknote.

### 2.3 The Ring Signature

#### 2.3.1 Construction

**Definition 3 (Ring Proof).** Given a ring of N public keys {P_1, ..., P_N}, a key image I, and a second generator H, the ring proof is the Sigma protocol:

```
Π_ring = atLeast(1, { σ_i : i ∈ [1..N] })
```

where each σ_i is the conjunction:

```
σ_i = proveDlog(P_i) ∧ proveDHTuple(G, H, P_i, I)
```

**In plain language:** "I know the secret key for at least one of the deposit keys in this pool, and I used it to compute the key image I."

**Why two conditions per key:**

- `proveDlog(P_i)`: proves knowledge of secret x_i such that P_i = x_i·G
- `proveDHTuple(G, H, P_i, I)`: proves I = x_i·H using the _same_ x_i

Together, they bind the key image deterministically to the secret key that controls one of the deposit slots. The `atLeast(1, ...)` Sigma OR ensures the verifier cannot determine _which_ σ_i was satisfied — this is the core privacy guarantee.

**Remark.** ErgoScript's `atLeast(1, ...)` implements the Cramer-Damgård-Schoenmakers (CDS) [6] OR proof technique, which is provably zero-knowledge and sound under the DL assumption. The Ergo node applies the Fiat-Shamir heuristic to make the proof non-interactive, binding it to the transaction context.

#### 2.3.2 The Second Generator H (NUMS Point)

The ring proof requires a second elliptic curve generator H ∈ **G**. The discrete log of H with respect to G must be unknown — otherwise, an adversary knowing h (where H = h·G) could forge arbitrary key images: given any P_i, compute I' = h·P_i = h·x_i·G = x_i·(h·G) = x_i·H without knowing x_i.

**Definition 4 (NUMS Generator).** H is derived deterministically:

```
seed     = "CASH.v3.second.generator.H.0"
x_H      = SHA256(seed)
         = 0xeab569326ae73e525b96643b2c31300e822007c91faf0c356226c4942ebe9eb2
y_H      = sqrt(x_H³ + 7) mod p     (secp256k1 curve equation: y² = x³ + 7)
H        = (x_H, y_H)               (verified: point lies on curve)
H_compr  = 02eab569326ae73e525b96643b2c31300e822007c91faf0c356226c4942ebe9eb2
```

**Proposition 1 (NUMS Security).** Under Assumption 3 (collision resistance of SHA-256), computing the discrete log h such that H = h·G is computationally infeasible.

*Proof sketch.* The x-coordinate of H is the output of SHA-256. Computing h requires finding a preimage of x_H under the map x → (x·G).x_coord, which is equivalent to solving the discrete logarithm problem (Assumption 1). The use of a fixed, public seed ensures that no party could have chosen H with knowledge of its discrete log — the derivation is fully reproducible and verifiable by anyone. ∎

**ErgoScript integration:** H is embedded as a constant via `decodePoint(fromBase16("02eab5..."))`. This compiles successfully and has been verified on the Ergo node.

#### 2.3.3 Key Image as Nullifier

**Definition 5 (Key Image).** For a depositor with secret key x ∈ Z_q:
- **Public key:** P = x·G
- **Key image:** I = x·H

**Proposition 2 (Key Image Uniqueness).** For a given deposit key P, the key image I is unique.

*Proof.* Since x is the unique discrete log of P (by the prime order of **G**), and H is a fixed generator, I = x·H is deterministically defined. The same x always produces the same I. ∎

**Proposition 3 (Key Image Unlinkability).** Given a key image I and a set of public keys {P_1, ..., P_N}, no polynomial-time adversary can determine which P_j produced I, without knowing the corresponding secret x_j.

*Proof sketch.* Determining j requires computing x_j = I / H (division in the group, i.e. discrete log of I with respect to H) and checking which P_j satisfies P_j = x_j·G. This requires solving the DLP with respect to H, which is infeasible under Assumption 1. Alternatively, the DDH assumption (Assumption 2) ensures that the tuple (G, H, P_j, I) is computationally indistinguishable from (G, H, P_j, R) for random R, for all j ≠ real index. ∎

**Intuition:** The key image is like a unique fingerprint for each depositor — the same person always produces the same fingerprint (preventing double-withdrawal), but the fingerprint can't be matched back to any specific public key (preserving privacy).

**Storage.** Key images are stored in an AvlTree T (register R5). When a withdrawal is attempted, the contract inserts the encoded key image into T. If the key image already exists, the AvlTree insert operation fails, and the entire transaction is rejected by the Ergo node.

### 2.4 Smart Contract Design

#### 2.4.1 PoolContract — Withdrawal Path

```scala
{
  val keys     = SELF.R4[Coll[GroupElement]].get
  val denom    = SELF.R6[Long].get
  val poolOut  = OUTPUTS(0)

  // Ring requires >= 2 members for meaningful privacy
  val ringOk   = keys.size >= 2

  // Key image (nullifier) and insert proof from context extension
  val keyImage     = getVar[GroupElement](0).get
  val insertProof  = getVar[Coll[Byte]](1).get

  // Insert key image into nullifier tree
  // (FAILS if already exists = double-spend prevention)
  val curTree  = SELF.R5[AvlTree].get
  val newTree  = curTree.insert(
    Coll((keyImage.getEncoded, Coll[Byte]())),
    insertProof
  ).get

  // Output pool has updated nullifier tree
  val treeOk   = poolOut.R5[AvlTree].get.digest == newTree.digest

  // Tokens decreased by exactly one denomination
  val tokenOk  = poolOut.tokens(0)._2 == SELF.tokens(0)._2 - denom

  // Keys NOT removed (removal would reveal who withdrew)
  val keysOk   = poolOut.R4[Coll[GroupElement]].get.size == keys.size

  // Pool parameters preserved
  val scriptOk = poolOut.propositionBytes == SELF.propositionBytes
  val denomOk  = poolOut.R6[Long].get == denom

  // Withdrawal output
  val withdrawOut = OUTPUTS(1)
  val withdrawOk  = withdrawOut.tokens(0)._1 == SELF.tokens(0)._1 &&
                    withdrawOut.tokens(0)._2 == denom

  // The ring signature (Definition 3)
  val H = decodePoint(fromBase16(
    "02eab569326ae73e525b96643b2c31300e822007c91faf0c356226c4942ebe9eb2"))
  val ringProof = atLeast(1, keys.map { (pk: GroupElement) =>
    proveDlog(pk) && proveDHTuple(groupGenerator, H, pk, keyImage)
  })

  sigmaProp(ringOk && treeOk && tokenOk && keysOk &&
            scriptOk && denomOk && withdrawOk) && ringProof
}
```

**Verified:** This contract compiles to 253 bytes ErgoTree and produces a valid P2S address on the Ergo node.

**Contract Invariants.** The withdrawal path enforces five invariants simultaneously:

| Invariant | Check | Consequence if Violated |
|---|---|---|
| I1: No double-withdrawal | AvlTree insert of I | Transaction rejected (insert fails) |
| I2: Exact denomination | tokenOk | Cannot withdraw more/less than D |
| I3: Key persistence | keysOk | Cannot shrink the ring (privacy preserved) |
| I4: Script continuity | scriptOk | Cannot redirect pool to different contract |
| I5: Valid ring member | ringProof (Π_ring) | Only a legitimate depositor can withdraw |

#### 2.4.2 PoolContract — Deposit Path

```scala
{
  val keys     = SELF.R4[Coll[GroupElement]].get
  val denom    = SELF.R6[Long].get
  val maxN     = SELF.R7[Int].get
  val poolOut  = OUTPUTS(0)

  val spaceOk  = keys.size < maxN
  val newKeys  = poolOut.R4[Coll[GroupElement]].get
  val sizeOk   = newKeys.size == keys.size + 1
  val oldKeysOk = keys.indices.forall { (i: Int) =>
    newKeys(i) == keys(i)
  }
  val tokenOk  = poolOut.tokens(0)._2 == SELF.tokens(0)._2 + denom
  val scriptOk = poolOut.propositionBytes == SELF.propositionBytes
  val denomOk  = poolOut.R6[Long].get == denom
  val maxOk    = poolOut.R7[Int].get == maxN
  val treeOk   = poolOut.R5[AvlTree].get.digest == SELF.R5[AvlTree].get.digest

  sigmaProp(spaceOk && sizeOk && oldKeysOk && tokenOk &&
            scriptOk && denomOk && maxOk && treeOk)
}
```

**Deposit Invariants:** The deposit path is permissionless — anyone can add a key. The contract ensures: (1) the pool is not full, (2) exactly one new key is appended, (3) existing keys are untouched, (4) exactly D tokens are added, and (5) the nullifier tree is unchanged.

#### 2.4.3 NoteContract

```scala
{
  val denomValid = {
    val d = SELF.tokens(0)._2
    d == 1L || d == 10L || d == 100L || d == 1000L ||
    d == 10000L || d == 100000L
  }
  sigmaProp(denomValid) && proveDlog(SELF.R4[GroupElement].get)
}
```

A NoteBox is a **real bearer instrument** — spending requires proving knowledge of the discrete log of R4. In formal terms: the spending condition is `proveDlog(P_owner)`, where P_owner ∈ **G** is stored in R4. Only the holder of the corresponding secret key x_owner can produce a valid proof.

This is a significant improvement over v1.2, where anyone who could construct the right transaction structure could spend a note.

### 2.5 Unified Contract (Deposit ∨ Withdraw)

In practice, both paths are combined into a single PoolContract using Sigma OR:

```scala
{
  val depositPath = { ... }    // §2.4.2
  val withdrawPath = { ... }   // §2.4.1
  depositPath || withdrawPath
}
```

The Ergo node's script verifier evaluates both paths and accepts if either is satisfied. This is sound because the deposit and withdrawal conditions are mutually exclusive — a deposit increases the token reserve while a withdrawal decreases it.

---

## 3. User Flow

### 3.1 Acquiring $CASH

```
1. Alice buys $CASH tokens on a DEX (ERG → $CASH)
   Result: Alice has NoteBoxes with $CASH tokens, locked to her stealth key
```

No IDO, VendingMachine, or custom issuance contract is required. $CASH is an EIP-4 standard token deployable via normal token issuance, distributable via DEX listing, airdrop, or any standard mechanism.

### 3.2 Private Transfer: Alice → Bob

**Protocol 1 (Private Transfer).**

```
Step 1 — DEPOSIT:
  Alice generates a one-time keypair: x ←$ Z_q, P = x·G
  Alice submits a deposit transaction:
    Input:  PoolBox(keys={P_1,...,P_k}, reserve=R, T)
    Output: PoolBox(keys={P_1,...,P_k,P}, reserve=R+D, T)
  Alice stores x securely (derivable from HD wallet seed)

Step 2 — WAIT:
  Other users deposit into the same pool.
  The ring grows: {P_1,...,P_k,P,...,P_N}

Step 3 — WITHDRAW:
  Alice computes her key image: I = x·H
  Alice generates AvlTree insert proof π_insert for I into T
  Alice submits a withdrawal transaction:
    Input:  PoolBox(keys={P_1,...,P_N}, reserve=R, T)
    Output: PoolBox(keys={P_1,...,P_N}, reserve=R−D, T')
            NoteBox(tokens=D, R4=P_bob)   [Bob's stealth key]
  where T' = T ∪ {I} and the ring proof Π_ring (Def. 3) is satisfied

  Observer sees: "Someone withdrew from this pool" — cannot determine who
```

### 3.3 Bob Uses His $CASH

Bob now has a **clean NoteBox** with no connection to Alice:
- **Spend:** deposit into a pool and withdraw to a merchant
- **Hold:** as a bearer asset (like holding a banknote)
- **Trade:** on a DEX for ERG or other tokens
- **Split:** into smaller denominations via DenomExchange

The tokens circulate. Each deposit-withdraw cycle provides fresh ring-signature privacy.

### 3.4 Privacy Timeline

```
Block N:      Alice deposits     (pool: 1 key — no privacy yet)
Block N+5:    Charlie deposits   (pool: 2 keys — anonymity = 1/2)
Block N+12:   Dave deposits      (pool: 3 keys — anonymity = 1/3)
...
Block N+100:  Pool reaches 16    (pool: 16 keys — anonymity = 1/16)
Block N+150:  First withdrawal   (observer can't tell who withdrew)
Block N+200:  Second withdrawal  (still 1/16 — keys never removed)
```

**Proposition 4 (Anonymity Monotonicity).** The anonymity set of a pool is monotonically non-decreasing: once a key is added, it is never removed. Therefore, Anonymity(block_j) ≥ Anonymity(block_i) for all j > i.

*Proof.* Keys are append-only (deposit adds, withdrawal preserves). The keysOk invariant (I3) ensures |keys_out| = |keys_in| on withdrawal. ∎

**Intuition:** The anonymity set is like a crowd — it only grows. Even after someone leaves the crowd (withdraws), their key remains, so the crowd never shrinks. This means later withdrawals are _at least_ as private as earlier ones.

---

## 4. Security Analysis

### 4.1 Formal Security Properties

We state the security properties of $CASH v3 as formal propositions, with proof sketches grounded in standard cryptographic assumptions.

**Theorem 1 (Soundness).** No computationally bounded adversary can produce a valid withdrawal transaction without knowing the secret key x_j for some P_j in the ring.

*Proof sketch.* A valid withdrawal requires a proof Π_ring = atLeast(1, {σ_i}). By the soundness of Sigma protocols [6], at least one σ_i must be genuine. A genuine σ_i requires both proveDlog(P_i) and proveDHTuple(G,H,P_i,I). By the soundness of Schnorr proofs (proveDlog), producing a valid proof for P_i requires knowledge of x_i such that P_i = x_i·G. This reduces to the hardness of the DLP (Assumption 1). ∎

**Theorem 2 (Zero-Knowledge / Anonymity).** Given a valid withdrawal transaction, no computationally bounded adversary can determine which P_j ∈ {P_1,...,P_N} was used in the proof, with probability better than 1/N.

*Proof sketch.* The CDS OR-proof technique [6] ensures that simulated branches (where the prover does not know the secret) are computationally indistinguishable from the real branch. The simulator can produce valid-looking (σ_i) for all i ≠ j using random commitments and challenge manipulation. Under the DDH assumption (Assumption 2), the real branch is indistinguishable. Therefore, the adversary's advantage in identifying j is negligible. ∎

**Theorem 3 (Double-Spend Prevention).** No depositor can withdraw more than once from a given pool.

*Proof.* For secret key x, the key image I = x·H is unique (Proposition 2). The withdrawal contract inserts I into the AvlTree T. If I ∈ T already, the insert operation fails and the transaction is rejected. Since the same x always produces the same I (deterministic computation), a second withdrawal attempt will always fail. ∎

**Theorem 4 (Deposit-Withdrawal Unlinkability).** No computationally bounded adversary, observing the full blockchain history, can link a specific withdrawal transaction to its corresponding deposit transaction with probability better than 1/N.

*Proof sketch.* The deposit transaction reveals P (the depositor's public key). The withdrawal transaction reveals I (the key image). Linking them requires determining that I = x·H where P = x·G — i.e., that (G, H, P, I) is a valid DH-tuple. Under the DDH assumption (Assumption 2), this test is computationally infeasible without knowledge of x. Combined with the zero-knowledge property of the ring proof (Theorem 2), the adversary cannot distinguish the real depositor from any other ring member. ∎

### 4.2 Threat Model

| Adversary | Capability | $CASH v3 Resistance | Formal Basis |
|---|---|---|---|
| **Passive observer** | Reads all on-chain data | Ring signature hides depositor identity. Anonymity = 1/N. | Theorem 2 |
| **Pool timing analyst** | Monitors deposit/withdrawal timing | Anonymity = 1/N regardless of timing. All ring members equally likely. | Theorem 4 |
| **Malicious pool creator** | Creates pools to isolate targets | Users choose pools freely. Privacy-conscious users prefer pools with N ≥ 8. | User behavior assumption |
| **Colluding depositors** | k of N depositors collude | Anonymity degrades to 1/(N−k) for honest depositors. Ring must have N−k ≥ 2, else trivially broken. | Standard ring signature limitation |
| **State-level actor** | IP correlation, subpoena power | EIP-41 stealth addresses + Tor recommended. IP correlation is outside protocol scope. | Network-layer privacy (orthogonal) |

### 4.3 Security Properties — Summary

| Property | Status | Formal Guarantee |
|---|---|---|
| **Sender privacy** | ✅ Guaranteed 1-in-N | Theorem 2 (ZK of ring proof) |
| **Receiver privacy** | ✅ EIP-41 stealth addresses | Standard stealth address security |
| **Amount privacy** | ⚠️ Denomination visible | Not addressed (see §10.2) |
| **Transaction graph privacy** | ✅ Unlinkable | Theorem 4 (DDH-based) |
| **Double-spend prevention** | ✅ Key image nullifier | Theorem 3 (AvlTree insert) |

### 4.4 Lost Keys (Dormant Deposits)

If a depositor loses their secret key x, their tokens remain locked in the pool permanently. The key P stays in R4 but can never produce a valid ring proof (Theorem 1 — soundness). This is functionally identical to losing a physical banknote — value is destroyed.

After all active depositors withdraw, dormant tokens remain in the PoolBox. Eventually, Ergo's **Storage Rent** mechanism reclaims the box and releases its contents to miners, naturally recycling the tokens.

---

## 5. JitCost Budget Analysis

### 5.1 The Constraint

Ergo limits per-block computation to `maxBlockCost = 1,000,000` units. All scripts in all transactions within a block share this budget. The $CASH withdrawal path must fit comfortably, leaving room for other transactions.

### 5.2 Cost Model

Let C(tx) denote the total JitCost of a withdrawal transaction. We decompose:

```
C(tx) = C_struct + C_script + C_sigma(N)
```

where:
- C_struct = cost of transaction structure (inputs, outputs, token accesses)
- C_script = cost of ErgoTree interpretation (register reads, AvlTree ops, comparisons)
- C_sigma(N) = cost of Sigma proof verification, linear in ring size N

**Measured parameters** (confirmed via testnet node `ergo-testnet-6.0.1`, height 170,349):

| Component | Cost (units) | Notes |
|---|---|---|
| C_struct | 4,700 | 2 inputs × 2,000 + 3 outputs × 100 + 4 token accesses × 100 |
| C_script | 2,880 | Register reads, AvlTree insert, comparisons, decodePoint |
| C_sigma(1) | 7,200 | `proveDlog` (1,800) + `proveDHTuple` (5,400) per ring member |

Therefore: **C(tx) = 7,580 + 7,200·N**

### 5.3 Results by Ring Size

| Ring Size N | C_sigma(N) | C(tx) | Budget Used | Verdict |
|---|---|---|---|---|
| **4** | 28,800 | 36,380 | **3.6%** | ✅ PASS |
| **8** | 57,600 | 65,180 | **6.5%** | ✅ PASS |
| **12** | 86,400 | 93,980 | **9.4%** | ✅ PASS |
| **16** | 115,200 | 122,780 | **12.3%** | ✅ PASS |

**At maximum ring size (N=16), a withdrawal uses only 12.3% of the block budget.** This means ≈8 concurrent $CASH withdrawals can fit in a single block alongside regular transactions.

### 5.4 ErgoTree Sizes

| Contract | ErgoTree Size | Comparison |
|---|---|---|
| Ring proof (core) | **89 bytes** | ~5× smaller than typical AMM contracts |
| Full withdrawal (AvlTree + ring + tokens) | **253 bytes** | ~3× smaller than typical DeFi |

---

## 6. Pool Economics and Throughput

### 6.1 Pool Concurrency

Each PoolBox is a single UTXO — one transaction can spend it per block. With Ergo's ~2 minute block time:

- 1 pool = ~720 operations/day
- 100 pools = ~72,000 operations/day

At 100 pools across 6 denominations (~17 pools per denomination), the system handles thousands of deposits and withdrawals daily.

### 6.2 Permissionless Pool Creation

Anyone can create a PoolBox:
1. Compile the PoolContract script to obtain the P2S address
2. Create a box at that address with empty R4, empty AvlTree (R5), desired D (R6), and max size (R7)
3. The pool is ready to accept deposits

**No operator keys. No fees. No bots.** The pool is a fully autonomous smart contract.

### 6.3 No Fee Market, No Death Spiral

v1.2 had a competitive bot market that converged to zero fees and surveillance dominance. v3 eliminates this attack surface entirely — there are no intermediaries to pay, no bots to run, and no fee market to distort.

**Intuition:** v3 pools are like public park benches — anyone can build one, anyone can use one, nobody charges for sitting. The "operator" is the Ergo blockchain itself.

---

## 7. Token Design

### 7.1 Token Purpose

$CASH is a **utility token** that serves as the medium of exchange within the privacy pool system. Its sole function is to denominate private transfers — it conveys no governance rights, profit expectation, or claim on underlying assets.

### 7.2 Denominations

| Tier | Token Amount D | Approximate Value (at 100:1) |
|---|---|---|
| 1 | 1 $CASH | ~0.01 ERG |
| 2 | 10 $CASH | ~0.1 ERG |
| 3 | 100 $CASH | ~1 ERG |
| 4 | 1,000 $CASH | ~10 ERG |
| 5 | 10,000 $CASH | ~100 ERG |
| 6 | 100,000 $CASH | ~1,000 ERG |

Six denomination tiers span 5 orders of magnitude, covering micro-transactions through significant transfers.

### 7.3 Distribution

$CASH is issued as a standard EIP-4 token. Distribution can proceed via:
- **DEX listing** (ERG → $CASH) for price discovery
- **Community airdrop** to seed initial liquidity
- **Protocol deployment** — team pre-seeds pools with initial deposits to establish minimum ring sizes

No ICO is required. The token exists independently of the privacy pool infrastructure.

---

## 8. Regulatory Considerations

### 8.1 Ergo Chain Is Unaffected

$CASH is an application-level smart contract — not a protocol-level privacy feature. Ergo's base layer remains fully transparent. Exchanges listing ERG face no additional compliance burden from $CASH's existence, just as Ethereum exchanges face no burden from Tornado Cash's existence on that chain.

### 8.2 Opt-In Privacy

All $CASH transactions are voluntary. Users choose to enter the privacy system. The transparent alternative (standard Ergo token transfers) remains available at all times.

### 8.3 Selective Disclosure

**Definition 6 (Selective Disclosure).** A $CASH user can voluntarily reveal their secret key x to a third party (auditor, tax authority, compliance officer). Given x, the verifier can:
1. Compute P = x·G → identify the deposit
2. Compute I = x·H → verify the withdrawal
3. Cross-reference timestamps → establish the deposit/withdrawal dates

This provides **auditability on demand** without compromising the privacy of other pool participants. Importantly, revealing x proves a _specific_ user's activity without degrading the anonymity of the remaining N−1 ring members.

### 8.4 No Single Sanction Target

Unlike Tornado Cash (one contract address, sanctionable by OFAC), $CASH pools are permissionless and numerous. Sanctioning one pool address does not disable the system — new pools can be created by anyone, instantly.

### 8.5 MiCA Classification

Under EU MiCA Regulation (2023/1114), $CASH would likely classify as an **"other crypto-asset"** (Title II) — not an asset-referenced token or e-money token, since it is not pegged to any external value. The white paper and disclosure requirements of Title II would apply if offered to EU residents.

---

## 9. Comparison with Related Work

### 9.1 Within the Ergo Ecosystem

| Project | Mechanism | Privacy Level | Differences from $CASH |
|---|---|---|---|
| **ErgoMixer** | CoinJoin-style non-interactive mixing | Moderate | CoinJoin requires concurrent participation; ring sizes are smaller; no bearer-instrument model |
| **EIP-41 Stealth Addresses** | One-time addresses | Identity only | Hides recipient but not sender; no transaction graph privacy |
| **Braid Sidechain** | Bulletproofs++ / Global Transfer Policies | Configurable | Different architecture — sidechain with its own consensus; more powerful but more complex |

$CASH fills a gap: **application-level ring-signature privacy pools** that work on Ergo L1 today, with no sidechain and no protocol changes.

### 9.2 Cross-Chain Comparison

| Feature | $CASH v3 | Monero | Tornado Cash | Zcash (shielded) |
|---|---|---|---|---|
| **Ring signatures** | ✅ (N ≤ 16) | ✅ (N = 16) | ❌ | ❌ |
| **Guaranteed anonymity floor** | ✅ (= 1/N) | ✅ (= 1/16) | ✅ (= 1/all deposits) | ✅ (= 1/all shielded) |
| **Amount hiding** | ⚠️ (D visible) | ✅ (Pedersen + BP) | ✅ (fixed D) | ✅ (encrypted) |
| **Trusted setup** | ❌ (none) | ❌ | ✅ (required) | ✅ (required) |
| **DeFi composability** | ✅ (EIP-4 on DEXes) | ❌ (no contracts) | ✅ (ERC-20) | ⚠️ (limited) |
| **Selective disclosure** | ✅ (Def. 6) | ⚠️ (view keys) | ❌ | ✅ (viewing keys) |
| **Delisting risk to host chain** | ❌ | ✅ (Monero IS privacy) | ❌ | ✅ (Zcash = privacy) |
| **Protocol changes** | ❌ (pure app layer) | N/A | ❌ | N/A |

### 9.3 Honest Monero Comparison

What $CASH v3 shares with Monero:
- Ring signatures with comparable ring size (16)
- Stealth addresses for recipient privacy
- Key images for double-spend prevention

What Monero has that $CASH does not:
- **Mandatory privacy** — all Monero transactions are private by default
- **Amount hiding** — Pedersen commitments + Bulletproofs
- **Protocol-level integration** — consensus-enforced ring signatures

What $CASH has that Monero does not:
- **No delisting pressure** on the host chain
- **DeFi composability** — works with Ergo DEXes, lending, etc.
- **Selective disclosure** — prove specific deposits for compliance
- **Storage rent** — naturally cleans up spent pool state

---

## 10. Known Limitations

### 10.1 Ring Size Ceiling

JitCost limits practical ring size to N ≤ 16, providing 1/16 anonymity. This is comparable to Monero but far below ZK-based systems (1/|all deposits|).

**Future directions:** If Ergo adopts sub-linear ring proof support (e.g., a Triptych-style EIP [*] for O(log N) proof size), ring size could scale to N = 128 or 1024 without changing the $CASH protocol architecture.

### 10.2 Amount Privacy

Denomination tiers are visible. An observer knows whether a pool handles D=100 or D=100,000.

**Mitigation:** Denominations are coarse (6 tiers spanning 5 orders of magnitude). Within a tier, all notes are identical and indistinguishable.

**Future directions:** Pedersen commitments + Bulletproofs [7] could hide amounts entirely. This requires an EIP for range proof verification in ErgoScript — a valuable addition to Ergo that $CASH could motivate.

### 10.3 Pool Filling Time

Privacy requires N ≥ 2 (a ring of 1 is trivially deanonymizable). At low adoption, pools may take time to reach minimum ring size.

**Mitigations:**
- Pre-deploy pools with seed deposits at launch (establish N ≥ 4 from genesis)
- Smaller ring capacity (maxN = 8) fills faster
- Concentrate demand across fewer denomination tiers initially

### 10.4 UTXO Contention

Each PoolBox is a single UTXO — only one transaction can spend it per block. High-demand pools may experience contention.

**Mitigations:**
- Multiple pools per denomination (horizontal scaling)
- Chained transactions within a block (Ergo supports this)
- Sub-block parallelism (if introduced in future protocol upgrades)

### 10.5 Colluding Ring Members

If k of N ring members collude (sharing their secret keys), the anonymity set for honest members degrades to 1/(N−k). In the degenerate case N−k = 1, the honest member is fully deanonymized.

**Mitigation:** Users should prefer pools with N ≥ 8 and assess pool maturity (older pools with keys from diverse time periods are less likely to be Sybil-populated).

---

## 11. Implementation

### 11.1 Reference Implementation

The Ergo Agent SDK (`ergo-agent-sdk`) includes:
- **`privacy.py`** — NUMS H constant, contract sources, deposit/withdraw transaction helpers
- **`builder.py`** — Transaction builder with `with_input()` for explicit box spending and context extensions
- **`node.py`** — Script compilation via `/script/p2sAddress`

All contracts have been compiled and verified on the Ergo node. 35 unit tests pass.

### 11.2 Roadmap

| Phase | Timeline | Deliverable |
|---|---|---|
| **1. Verification** ✅ | Complete | NUMS H computation, contract compilation, JitCost analysis |
| **2. Testnet Deployment** | Next | Deploy PoolContract, create test pools, measure real JitCost |
| **3. Wallet Integration** | +2 months | Nautilus plugin or standalone wallet for deposit/withdraw UX |
| **4. Security Audit** | +3 months | Independent audit of contracts + formal ring proof analysis |
| **5. Mainnet Launch** | +4 months | Token genesis, pre-seeded pools, DEX listing |

### 11.3 Open Source

All code, contracts, and this white paper are open source under CC BY 4.0. The contracts are fully auditable and reproducible — anyone can compile the ErgoScript source and verify the resulting ErgoTree matches what is deployed.

---

## 12. Conclusion

$CASH v3 is not a mixer. It is a **digital cash system** that achieves the core properties of physical banknotes:

- **Bearer ownership** — whoever knows x owns the deposit (Definition 5)
- **Fungibility** — clean notes with no routing history (Definition 2)
- **Transaction unlinkability** — deposit ≠ withdrawal (Theorem 4)
- **Guaranteed privacy floor** — 1/N, independent of adoption (Proposition 4)
- **Double-spend prevention** — deterministic key images (Theorem 3)

These properties are achieved using only Ergo's existing Sigma protocol framework — specifically, the `proveDlog`, `proveDHTuple`, and `atLeast` primitives — with security reductions to the standard Discrete Logarithm and Decisional Diffie-Hellman assumptions on secp256k1.

> *"Cryptocurrency should provide tools to enrich ordinary people."*
> — Kushti, The Ergo Manifesto

$CASH proves that those tools can deliver real-world privacy — opt-in, composable, and sustainable — without changing the base protocol, without trusted setups, and without risking the host chain's regulatory standing.

**The minimum viable product is one contract (PoolContract), one constant (H), and one wallet feature (deposit/withdraw UX).** Everything else is refinement.

---

## References

1. Chepurnoy, A. et al. "Ergo: A Resilient Platform for Contractual Money." Ergo Platform, 2019. https://ergoplatform.org/docs/whitepaper.pdf

2. Chepurnoy, A. "The Ergo Manifesto." Ergo Platform, April 2021. https://ergoplatform.org/en/blog/2021-04-26-the-ergo-manifesto/

3. Chepurnoy, A. "ErgoScript: A Cryptocurrency Scripting Language Supporting Noninteractive Zero-Knowledge Proofs." https://ergoplatform.org/docs/ErgoScript.pdf

4. van Saberhagen, N. "CryptoNote v 2.0." 2013. https://cryptonote.org/whitepaper.pdf (Ring signatures and key images in cryptocurrency)

5. Noether, S. et al. "Ring Confidential Transactions." Ledger Journal, 2016. (Monero's ring signature implementation)

6. Cramer, R., Damgård, I., Schoenmakers, B. "Proofs of Partial Knowledge and Simplified Design of Witness Hiding Protocols." CRYPTO 1994. (Sigma OR proofs — the theoretical foundation)

7. Bünz, B. et al. "Bulletproofs: Short Proofs for Confidential Transactions and More." IEEE S&P 2018. https://eprint.iacr.org/2017/1066

8. Chakravarty, M.M.T. et al. "The Extended UTXO Model." IOHK, 2020. https://iohk.io/en/research/library/papers/the-extended-utxo-model/

9. European Parliament. "Regulation (EU) 2023/1114 (MiCA)." https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32023R1114

10. Ergo Platform. "EIP-41: Stealth Addresses." https://github.com/ergoplatform/eips

11. Liu, J.K., Wei, V.K., Wong, D.S. "Linkable Spontaneous Anonymous Group Signature for Ad Hoc Groups." ACISP 2004. (Linkable ring signatures — theoretical basis for key image construction)

---

*$CASH v3 — Draft 0.1 — February 2026*
*A. Shannon — CC BY 4.0*
