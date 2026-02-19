#!/usr/bin/env python3
"""
Example 08: Safety config demo.

Demonstrates how the SafetyConfig layer protects against
runaway agents, accidental overspending, and unauthorized contracts.

Usage:
    python examples/08_safety_demo.py
"""

from ergo_agent.tools.safety import SafetyConfig, SafetyViolation

# Create a strict safety config
safety = SafetyConfig(
    max_erg_per_tx=5.0,
    max_erg_per_day=20.0,
    allowed_contracts=["spectrum"],
    rate_limit_per_hour=3,
    dry_run=True,  # no real transactions
)

print("=== Safety Config Demo ===")
print()

# Test 1: Normal transaction (passes)
print("[Test 1] Send 2 ERG to a P2PK address")
try:
    safety.validate_send(amount_erg=2.0, destination="9fRw3bMzSNBuZNmBJd3VAJGf7XQmFfeiebJ989LvTNdxmcz3vEd")
    safety.validate_rate_limit()
    safety.record_action(erg_spent=2.0)
    print("  -> PASSED (2 ERG within all limits)")
except SafetyViolation as e:
    print(f"  -> BLOCKED: {e}")

# Test 2: Per-transaction limit (blocked)
print()
print("[Test 2] Try to send 10 ERG (exceeds 5 ERG per-tx limit)")
try:
    safety.validate_send(amount_erg=10.0, destination="9fRw3bMzSNBuZNmBJd3VAJGf7XQmFfeiebJ989LvTNdxmcz3vEd")
    print("  -> PASSED")
except SafetyViolation as e:
    print(f"  -> BLOCKED: {e}")

# Test 3: Unknown contract (blocked)
print()
print("[Test 3] Try to interact with unknown contract")
try:
    safety.validate_send(amount_erg=1.0, destination="some_unknown_contract_address")
    print("  -> PASSED")
except SafetyViolation as e:
    print(f"  -> BLOCKED: {e}")

# Test 4: Rate limiting
print()
print("[Test 4] Rapid-fire actions (rate limit = 3/hour)")
for i in range(4):
    try:
        safety.validate_rate_limit()
        safety.record_action(erg_spent=1.0)
        print(f"  Action {i+1}: PASSED")
    except SafetyViolation as e:
        print(f"  Action {i+1}: BLOCKED ({e})")

# Show final status
print()
print("=== Current Status ===")
status = safety.get_status()
for key, value in status.items():
    print(f"  {key}: {value}")
