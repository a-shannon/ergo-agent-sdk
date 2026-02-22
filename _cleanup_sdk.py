"""
SDK Cleanup Script: Remove all $CASH references from the Ergo Agent SDK.
Makes the SDK a generic Ergo Python toolkit with no project-specific naming.
"""
import os
import re
import shutil

SDK_ROOT = r"C:\Users\louis\EUROBC SAS\ALTALEO - Documents\ANTIGRAVITY\ergo\ergo-agent-sdk"

# ── 1. File renames ─────────────────────────────────────────────────────────
FILE_RENAMES = {
    "src/ergo_agent/defi/cash_v3.py": "src/ergo_agent/defi/privacy_pool.py",
    "tests/unit/test_cash_client.py": "tests/unit/test_privacy_pool_client.py",
    "tests/unit/test_cash_vlq.py": "tests/unit/test_privacy_vlq.py",
    "tests/unit/test_safety_cash.py": "tests/unit/test_safety_privacy.py",
    "tests/integration/test_cash_lifecycle.py": "tests/integration/test_privacy_lifecycle.py",
    "tests/integration/test_cash_adversarial.py": "tests/integration/test_privacy_adversarial.py",
    "tests/integration/test_cash_advanced_security.py": "tests/integration/test_privacy_advanced_security.py",
    "tests/verify_cash_tools.py": "tests/verify_privacy_tools.py",
    "examples/15_ergo_cash_v3_ring_scanner.py": "examples/15_privacy_pool_scanner.py",
    "examples/16_cash_v3_autonomous_agent.py": "examples/16_privacy_pool_agent.py",
    "docs/cash-usage-guide.md": "docs/privacy-pool-guide.md",
    "docs/cash-security-guide.md": "docs/privacy-security-guide.md",
}

# ── 2. Content replacements (order matters: longer patterns first) ──────────
# We use a list of tuples so longer/more-specific patterns are matched first.
CONTENT_REPLACEMENTS = [
    # Class / module names
    ("CashV3Client", "PrivacyPoolClient"),
    ("cash_v3", "privacy_pool"),
    ("CashV3", "PrivacyPool"),
    
    # Tool names (agent tool definitions)
    ("get_cash_pools", "get_privacy_pools"),
    ("deposit_cash_to_pool", "deposit_to_privacy_pool"),
    ("withdraw_cash_privately", "withdraw_from_privacy_pool"),
    
    # Docstring / description references
    ("$CASH v3", "privacy pool"),
    ("$CASH", "privacy pool"),
    ("Ergo Cash", "Ergo privacy pool"),
    
    # Safety config allowed contracts
    # Use word-boundary-aware replacement done separately below

    # File path references in imports/configs
    ("cash-usage-guide", "privacy-pool-guide"),
    ("cash-security-guide", "privacy-security-guide"),
    ("cash-v3-whitepaper", "privacy-pool-whitepaper"),
    ("ergo_cash_v3_ring_scanner", "privacy_pool_scanner"),
    ("cash_v3_autonomous_agent", "privacy_pool_agent"),
    
    # Misc
    ("verify_cash_tools", "verify_privacy_tools"),
    ("test_cash_client", "test_privacy_pool_client"),
    ("test_cash_vlq", "test_privacy_vlq"),
    ("test_safety_cash", "test_safety_privacy"),
    ("test_cash_lifecycle", "test_privacy_lifecycle"),
    ("test_cash_adversarial", "test_privacy_adversarial"),
    ("test_cash_advanced_security", "test_privacy_advanced_security"),
    ("cash_token_id", "pool_token_id"),
    
    # The nav label in mkdocs
    ('"$CASH Privacy Protocol"', '"Privacy Protocol"'),
    ("$CASH Privacy Protocol", "Privacy Protocol"),
]

# These are standalone word replacements using regex word boundaries
WORD_REPLACEMENTS = [
    # In allowed_contracts lists: "cash" → "privacy_pool"
    # But be careful not to replace inside the crypto seed string
]

# Files/patterns that should NOT be modified
SKIP_PATTERNS = [
    "node_modules",
    "__pycache__",
    ".git",
    "_cleanup_sdk.py",
    "site/",
]

# The crypto seed must be preserved
CRYPTO_SEED = "CASH.v3.second.generator.H.0"

EXTENSIONS = {".py", ".md", ".yml", ".yaml", ".toml", ".txt", ".cfg", ".json"}


def should_skip(filepath):
    for p in SKIP_PATTERNS:
        if p in filepath:
            return True
    return False


def rename_files():
    """Rename files according to the mapping."""
    renamed = []
    for old_rel, new_rel in FILE_RENAMES.items():
        old_abs = os.path.join(SDK_ROOT, old_rel)
        new_abs = os.path.join(SDK_ROOT, new_rel)
        if os.path.exists(old_abs):
            os.makedirs(os.path.dirname(new_abs), exist_ok=True)
            shutil.move(old_abs, new_abs)
            renamed.append(f"  {old_rel} -> {new_rel}")
        else:
            renamed.append(f"  SKIP (not found): {old_rel}")
    return renamed


def replace_in_file(filepath):
    """Apply content replacements to a single file."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return False

    original = content

    # Apply ordered replacements but protect the crypto seed
    placeholder = "___CRYPTO_SEED_PROTECTED___"
    content = content.replace(CRYPTO_SEED, placeholder)

    for old, new in CONTENT_REPLACEMENTS:
        content = content.replace(old, new)

    # Handle standalone "cash" in allowed_contracts lists
    # Pattern: "cash" as a standalone string in Python list contexts
    content = re.sub(r'"cash"', '"privacy_pool"', content)
    # Also handle in docstrings where 'cash' appears as a standalone word
    # But NOT inside compound words like "broadcast" etc.
    # Only replace standalone cash references in specific contexts
    content = re.sub(r'destination="cash"', 'destination="privacy_pool"', content)
    content = re.sub(r"destination='cash'", "destination='privacy_pool'", content)
    
    # Replace "cash" in test assertion strings
    content = re.sub(r'in t\["function"\]\["name"\]', 'in t["function"]["name"]', content)
    content = content.replace('"cash" in t["function"]["name"]', '"privacy" in t["function"]["name"]')
    content = content.replace('"cash" in t["name"]', '"privacy" in t["name"]')
    content = content.replace('"cash" in t.name', '"privacy" in t.name')
    
    # Replace cash_tools_ prefix
    content = content.replace("cash_tools_", "privacy_tools_")

    # Replace "$CASH-TEST" token name in tests  
    content = content.replace("$CASH-TEST", "$PP-TEST")

    # Restore the crypto seed
    content = content.replace(placeholder, CRYPTO_SEED)

    if content != original:
        with open(filepath, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        return True
    return False


def process_directory():
    """Walk the SDK directory and apply replacements."""
    changed = []
    for root, dirs, files in os.walk(SDK_ROOT):
        # Skip unwanted directories
        dirs[:] = [d for d in dirs if not should_skip(os.path.join(root, d))]
        for fname in files:
            filepath = os.path.join(root, fname)
            if should_skip(filepath):
                continue
            _, ext = os.path.splitext(fname)
            if ext not in EXTENSIONS:
                continue
            if replace_in_file(filepath):
                rel = os.path.relpath(filepath, SDK_ROOT)
                changed.append(f"  {rel}")
    return changed


def delete_whitepaper():
    """Remove the $CASH whitepaper from the SDK (it belongs to the Midday project)."""
    wp = os.path.join(SDK_ROOT, "docs", "whitepapers", "cash-v3-whitepaper.md")
    if os.path.exists(wp):
        os.remove(wp)
        return True
    # Check if it was already renamed
    wp2 = os.path.join(SDK_ROOT, "docs", "whitepapers", "privacy-pool-whitepaper.md")
    if os.path.exists(wp2):
        os.remove(wp2)
        return True
    return False


if __name__ == "__main__":
    print("=" * 60)
    print("SDK CLEANUP: Removing $CASH references")
    print("=" * 60)
    
    print("\n1. Renaming files...")
    renames = rename_files()
    for r in renames:
        print(r)
    
    print(f"\n2. Replacing content in {len(EXTENSIONS)} file types...")
    changed = process_directory()
    print(f"   Modified {len(changed)} files:")
    for c in changed:
        print(c)
    
    print("\n3. Removing whitepaper from SDK...")
    if delete_whitepaper():
        print("   Deleted docs/whitepapers/cash-v3-whitepaper.md")
    else:
        print("   Whitepaper not found (already removed?)")
    
    print("\n" + "=" * 60)
    print("DONE. Run 'pytest tests/' to verify.")
    print("=" * 60)
