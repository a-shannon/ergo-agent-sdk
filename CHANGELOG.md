# Changelog

All notable changes to the `ergo-agent-sdk` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0] - 2026-02-23

### Added
- **PrivacyPoolV6 contract integration**: Unified lazy-evaluation contract replaces separate v5 deposit/withdrawal scripts.
- **AvlTree nullifier set (R5)**: Key images are stored in an authenticated AVL+ tree instead of `Coll[GroupElement]`. O(log n) insert proof scales to thousands of withdrawals.
- **Key image computation**: `compute_key_image(secret_hex)` derives `M = secret × H` on secp256k1.
- **AvlTree proof generation**: `generate_avl_insert_proof()` via PyO3 `ergo_avltree` extension.
- **Context extension serialization**: `serialize_context_extension()` for Sigma-typed GroupElement and Coll[Byte] vars.
- **Auto-generated secrets on deposit**: `deposit_to_privacy_pool()` generates and returns a fresh secret+public key pair.
- **Secret-based withdrawal flow**: `withdraw_from_privacy_pool()` accepts `secret_key` (not `key_image`); all cryptographic operations are handled internally.
- **Privacy timing safety guards**: `SafetyConfig` now includes `min_withdrawal_delay_blocks` (100) and `min_pool_ring_size` (4).

### Changed
- `build_withdrawal_tx()` in `PrivacyPoolClient` now accepts `secret_hex` instead of `key_image`.
- `_check_key_image_not_spent()` handles both AvlTree (type `0x64`) and legacy `Coll[GroupElement]` R5 formats.
- Tool schemas (OpenAI, LangChain, Anthropic) updated: `key_image` parameter replaced by `secret_key`.
- Withdrawal note amount is now exact denomination (removed 99% fee split from v5).
- Documentation fully updated: privacy-pool-guide, security guide, architecture, API reference.

### Fixed
- Silent `Int == Long → false` comparison in contract via explicit `.toInt` cast.
- `NullPointerException` during deposits caused by strict val evaluation of `OUTPUTS(1).tokens` (fixed via lazy `if/else` in PrivacyPoolV6).

## [0.5.0] - 2026-02-19

### Added
- **Privacy Pool Client (`PrivacyPoolClient`)**: Full support for ring-signature privacy pools (deposit, withdraw, health monitoring).
- **Explicit inputs + context extensions**: `TransactionBuilder.with_input(box, extension=...)` for contract-driven transactions.
- **EIP-004 token minting**: `TransactionBuilder.mint_token()` and `ErgoToolkit.mint_token()`.
- **Pool health analytics**: `evaluate_pool_health()` with privacy scoring, duplicate key detection, and risk flags.
- **Safety validations**: Point format validation, banned key detection, duplicate key checks, pool capacity pre-checks.
- **Agent tools**: `get_privacy_pools`, `deposit_to_privacy_pool`, `withdraw_from_privacy_pool` for all 3 LLM frameworks.

### Changed
- `get_unspent_boxes` defaults to `/blockchain/box/unspent/byAddress` for node-validated UTXO selection.
- `Wallet._sign_via_node` uses `/utxo/withPool/byId/` for mempool-aware box fetching.

## [0.4.0] - 2026-02-10

### Added
- **Stealth Key Cryptography**: SECP256k1 stealth key generation and Diffie-Hellman shared secret derivation.
- **Relayer API Server**: FastAPI application for integrating the privacy pool frontend with the node.
- **Register Decoders**: Handling of VLQ-encoded token amounts and custom R6/R7 protocol constraints.

### Fixed
- Addressed stale internal UTXO state during sequential transactions by adding block confirmation delays.

## [0.3.0] - 2025-XX-XX
- Initial support for core Ergo functions, DEX clients, tokens, and basic agent tools.
