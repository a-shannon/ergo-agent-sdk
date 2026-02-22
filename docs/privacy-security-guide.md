# Privacy Pool Security Guide

This document summarizes the threat model, hardening measures, and best practices for the privacy pool protocol.

## Threat Model Summary

The privacy pool protocol was subjected to a comprehensive security analysis covering 5 categories:

| Category | Findings | Status |
|----------|----------|--------|
| Cryptographic Edge Cases | 4 | ✅ Fixed in v4 |
| Input Sanitization | 3 | ✅ Fixed in SDK |
| Anonymity Set Quality | 3 | ✅ Mitigated |
| Pool Economics | 4 | ✅ Addressed |
| Privacy Leakage | 3 | ✅ Mitigated |

## Contract Guards (PrivacyPoolV4.es)

The v4 contract includes 5 hardened guards:

1. **`uniqueKeyOk`** — Prevents duplicate stealth keys in R4 ring
2. **`newKeyValid`** — Blocks `groupGenerator` as a deposit key
3. **`keyImageSafe`** — Blocks `groupGenerator` as a key image (prevents nullifier poisoning)
4. **`keyImageNotH`** — Blocks the `H` constant as a key image
5. **`keysContentOk`** — Ensures full R4 content equality on withdrawals (not just size)

## SDK Validations

The Python SDK (`PrivacyPoolClient`) performs pre-flight checks before building transactions:

- **Point format validation** — 66-char hex, `02`/`03` prefix, valid hex
- **Banned key detection** — Rejects `groupGenerator` and `H_CONSTANT`
- **Duplicate key detection** — Parses R4 to check for existing keys
- **Double-spend prevention** — Checks R5 nullifier list before withdrawal
- **Pool capacity pre-check** — Refuses deposits to full pools

## Privacy Best Practices

!!! warning "For Depositors"
    - Generate fresh stealth keys for every deposit
    - Never reuse a stealth key across pools
    - Wait for the pool to grow before withdrawing

!!! warning "For Withdrawers"
    - Use a **virgin address** (never used before) as the recipient
    - Wait at least **2 blocks** after your deposit before withdrawing
    - Use Tor or a VPN when communicating with the relayer
    - Check `evaluate_pool_health()` — avoid pools with `CRITICAL` privacy score

!!! danger "Known Limitations"
    - Ring size is capped at 16 — anonymity is bounded
    - Timing analysis can correlate deposits/withdrawals if done immediately
    - The relayer can see the withdrawal request (use Tor for max privacy)
    - On-chain metadata leakage through ERG change amounts

## Relayer Security

The relayer service (`api/server.py`) implements:

- **Request serialization** via `asyncio.Lock` — prevents UTXO contention
- **Privacy-preserving logging** — IP addresses are never logged
- **Auto-retry on UTXO contention** — 3 attempts with 5s backoff
- **Input validation passthrough** — SDK validations apply server-side
