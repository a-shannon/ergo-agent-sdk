# Privacy Pool Security Guide

This document summarizes the threat model, hardening measures, and best practices for the privacy pool protocol.

## Threat Model Summary

The privacy pool protocol was subjected to a comprehensive security analysis covering 5 categories:

| Category | Findings | Status |
|----------|----------|--------|
| Cryptographic Edge Cases | 4 | ✅ Fixed in PrivacyPoolV6 |
| Input Sanitization | 3 | ✅ Fixed in SDK |
| Anonymity Set Quality | 3 | ✅ Mitigated |
| Pool Economics | 4 | ✅ Addressed |
| Privacy Leakage | 3 | ✅ Mitigated |

## Contract Guards (PrivacyPoolV6.es)

The PrivacyPoolV6 contract uses a **unified lazy-evaluation** architecture with three paths (deposit, withdrawal, renewal) determined by `tokenDiff`:

### Withdrawal Path Guards

1. **`keyImageSafe`** — Blocks `groupGenerator` as a key image (prevents nullifier poisoning)
2. **`keyImageNotH`** — Blocks the `H` constant as a key image
3. **`treeOk`** — Verifies the AvlTree insert proof: the new nullifier tree digest in the output must match the result of inserting the key image
4. **`withdrawOk`** — Ensures the withdrawal note receives the exact denomination (no fee deduction)
5. **Ring Signature** — `atLeast(1, poolKeys.map(...))` with `proveDlog` + `proveDHTuple` proves membership without revealing which key

### Deposit Path Guards

1. **`spaceOk`** — New key count must not exceed `maxN` (register R7)
2. **`oldKeysOk`** — Existing keys in R4 must be preserved in order
3. **`newKeyValid`** — New key must not be `groupGenerator`
4. **`uniqueKeyOk`** — New key must not duplicate any existing key
5. **`treeOk`** — AvlTree nullifier set (R5) must remain unchanged during deposits

### AvlTree Nullifier Set (R5)

The v6 contract replaced the previous `Coll[GroupElement]` nullifier list with an **authenticated AVL+ tree** (AvlTree). Benefits:

- **O(log n) insert proof** — scales to thousands of withdrawals
- **Tamper-proof** — digest-based verification prevents nullifier manipulation
- **Node-validated** — the Ergo node validates the full tree proof during signing

The SDK generates insert proofs via the `ergo_avltree` Python extension (PyO3 wrapper around Rust implementation).

## SDK Validations

The Python SDK (`PrivacyPoolClient`) performs pre-flight checks before building transactions:

- **Point format validation** — 66-char hex, `02`/`03` prefix, valid hex
- **Banned key detection** — Rejects `groupGenerator` and `H_CONSTANT` for both deposits and withdrawals
- **Duplicate key detection** — Parses R4 to check for existing keys before deposit
- **Double-spend prevention** — Validates key image not already in R5 AvlTree (deferred to node validator for full tree verification)
- **Pool capacity pre-check** — Refuses deposits to full pools
- **Key image computation** — `compute_key_image(secret_hex)` derives `M = secret × H` internally
- **AvlTree proof generation** — `generate_avl_insert_proof()` creates the insert proof and new digest

## Privacy Best Practices

!!! warning "For Depositors"
    - Generate fresh stealth keys for every deposit (`generate_fresh_secret()`)
    - **Save your secret key** — it is required for withdrawal and cannot be recovered
    - Never reuse a stealth key across pools
    - Wait for the pool to grow before withdrawing

!!! warning "For Withdrawers"
    - Use a **virgin address** (never used before) as the recipient
    - Wait at least **100 blocks** after your deposit before withdrawing
    - Use Tor or a VPN when communicating with the relayer
    - Check `evaluate_pool_health()` — avoid pools with `CRITICAL` privacy score

!!! danger "Known Limitations"
    - Ring size is capped at 16 — anonymity is bounded
    - Timing analysis can correlate deposits/withdrawals if done immediately
    - The relayer can see the withdrawal request (use Tor for max privacy)
    - On-chain metadata leakage through ERG change amounts
    - The v6 contract withdraws the exact denomination (no fee deduction)

## Relayer Security

The relayer service (`api/server.py`) implements:

- **Request serialization** via `asyncio.Lock` — prevents UTXO contention
- **Privacy-preserving logging** — IP addresses are never logged
- **Auto-retry on UTXO contention** — 3 attempts with 5s backoff
- **Input validation passthrough** — SDK validations apply server-side
