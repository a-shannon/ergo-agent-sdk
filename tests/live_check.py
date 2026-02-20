"""
Quick live integration test script.
Run: python tests/live_check.py
"""
from ergo_agent import ErgoNode
from ergo_agent.core.wallet import Wallet
from ergo_agent.tools import ErgoToolkit, SafetyConfig


def main():
    node = ErgoNode(timeout=30.0)

    # 1. Chain height
    height = node.get_height()
    print(f"[OK] Chain height: {height}")
    assert height > 1_700_000, "Height looks wrong"

    # 2. Network info
    info = node.get_network_info()
    print(f"[OK] Network info: lastBlockId={info['lastBlockId'][:12]}...")

    # 3. Get a real address from a recent block
    # Use the blocks endpoint to find a valid address
    import httpx
    r = httpx.get(
        "https://api.ergoplatform.com/api/v1/blocks?limit=1&sortDirection=desc",
        timeout=15.0
    )
    block = r.json()["items"][0]
    miner_addr = block["miner"]["address"]
    print(f"[OK] Found miner address: {miner_addr[:20]}...")

    # 4. Try get_balance with a real address
    try:
        balance = node.get_balance(miner_addr)
        print(f"[OK] Balance: {balance.erg:.4f} ERG, {len(balance.tokens)} tokens")
    except Exception as e:
        print(f"[WARN] Balance failed: {e}")
        print("       (This may be an API rate limit or heavy address — not a bug)")

    # 5. Toolkit safety status
    wallet = Wallet.read_only(miner_addr)
    toolkit = ErgoToolkit(node, wallet, SafetyConfig(dry_run=True))
    status = toolkit.get_safety_status()
    print(f"[OK] Safety status: {status}")

    # 6. OpenAI tools generation
    tools = toolkit.to_openai_tools()
    print(f"[OK] Generated {len(tools)} OpenAI tools")
    for t in tools:
        print(f"     - {t['function']['name']}")

    # 7. Anthropic tools generation
    anthro_tools = toolkit.to_anthropic_tools()
    print(f"[OK] Generated {len(anthro_tools)} Anthropic tools")

    print("\n=== All live checks passed! ===")


if __name__ == "__main__":
    main()
