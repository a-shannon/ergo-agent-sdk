# Changelog

All notable changes to the `ergo-agent-sdk` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - Unreleased

### Added
- **privacy pool Protocol Client (`PrivacyPoolClient`)**: Full support for privacy pools (deploy, deposit, withdraw, health monitoring).
- **Stealth Key Cryptography**: SECP256k1 stealth key generation and Diffie-Hellman shared secret derivation.
- **Relayer API Server**: FastAPI application for integrating the privacy pool frontend with the node.
- **Agent Tools (`tools.privacy_pool`)**: `get_privacy_pools`, `deposit_to_privacy_pool`, `withdraw_from_privacy_pool` for Langchain/OpenAI/Anthropic tool sets.
- **Safety Mitigations (`SafetyConfig`)**: Configurable blocks delays, deterministic change obfuscation, and pool ring size checks during withdrawals.
- **Register Decoders**: Handling of VLQ-encoded token amounts and custom R6/R7 protocol constraints.

### Changed
- `get_unspent_boxes` in `ErgoNode` now defaults to `/blockchain/box/unspent/byAddress` for instantaneous, node-validated UTXO selection (bypass explorer indexing lag).
- `Wallet._sign_via_node` now queries `/utxo/withPool/byId/` for mempool-aware box fetching, eliminating double-spending bugs in sequential transactions.
- Unified `test_battery` and `lifecycle_test` scripts to reflect a fully validated 18/19 integration test suite.

### Fixed
- Addressed stale internal UTXO state during sequential transactions by adding block confirmation delays.

## [0.3.0] - 2024-XX-XX
- Initial support for core Ergo functions, DEX clients, tokens, and basic agent tools.
