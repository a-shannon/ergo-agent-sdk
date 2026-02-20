# API Reference

Complete reference for all public classes and methods.

---

## Core

### ErgoNode

::: ergo_agent.core.node.ErgoNode
    options:
      members:
        - __init__
        - get_height
        - get_network_info
        - get_balance
        - get_unspent_boxes
        - get_transaction_history
        - get_mempool_transactions
        - get_oracle_pool_box
        - submit_transaction
        - close

### Wallet

::: ergo_agent.core.wallet.Wallet
    options:
      members:
        - read_only
        - from_node_wallet
        - from_mnemonic
        - address
        - sign_transaction

### TransactionBuilder

::: ergo_agent.core.builder.TransactionBuilder
    options:
      members:
        - __init__
        - send
        - send_token
        - send_funds
        - mint_token
        - add_output_raw
        - with_input
        - build

### Address Utilities

::: ergo_agent.core.address
    options:
      members:
        - is_valid_address
        - validate_address
        - is_mainnet_address
        - is_p2pk_address
        - get_address_type
        - address_to_ergo_tree
        - AddressError

### Privacy Protocols

::: ergo_agent.core.privacy
    options:
      members:
        - find_optimal_pool
        - build_pool_deposit_tx
        - build_pool_withdraw_tx
        - NUMS_H_HEX

### Data Models

::: ergo_agent.core.models.Box

::: ergo_agent.core.models.Balance

::: ergo_agent.core.models.Token

::: ergo_agent.core.models.SwapQuote

::: ergo_agent.core.models.Transaction

---

## DeFi

### OracleReader

::: ergo_agent.defi.oracle.OracleReader
    options:
      members:
        - __init__
        - get_erg_usd_price
        - get_erg_usd_nanoerg_per_usd
        - get_oracle_box_id
        - get_price_history

### SpectrumDEX

::: ergo_agent.defi.spectrum.SpectrumDEX
    options:
      members:
        - __init__
        - get_pools
        - get_erg_price_in_sigusd
        - get_quote
        - build_swap_order
        - close

---

## Tools

### ErgoToolkit

::: ergo_agent.tools.toolkit.ErgoToolkit
    options:
      members:
        - __init__
        - get_wallet_balance
        - get_erg_price
        - get_swap_quote
        - get_mempool_status
        - get_safety_status
        - send_erg
        - swap_erg_for_token
        - execute_tool
        - to_openai_tools
        - to_anthropic_tools
        - to_langchain_tools

### SafetyConfig

::: ergo_agent.tools.safety.SafetyConfig
    options:
      members:
        - validate_send
        - validate_rate_limit
        - record_action
        - get_status

::: ergo_agent.tools.safety.SafetyViolation
