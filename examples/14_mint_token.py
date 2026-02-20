import asyncio
import os
import sys

from ergo_agent.core.node import ErgoNode
from ergo_agent.core.wallet import ErgoWallet
from ergo_agent.tools.toolkit import ErgoToolkit

async def main():
    if not os.getenv("ERGO_NODE_URL") or not os.getenv("ERGO_WALLET_MNEMONIC"):
        print("Please set ERGO_NODE_URL and ERGO_WALLET_MNEMONIC environment variables.")
        sys.exit(1)
    node = ErgoNode(os.getenv("ERGO_NODE_URL"))
    wallet = ErgoWallet(os.getenv("ERGO_WALLET_MNEMONIC"))
    toolkit = ErgoToolkit(node=node, wallet=wallet)

    print("Generating a test AgentCoin...")
    
    # We will do a dry-run first
    toolkit._safety.dry_run = True
    res = toolkit.mint_token(
        name="AgentCoin",
        description="A test utility token minted by the Ergo Agent Framework.",
        amount=1000000,
        decimals=4,
    )
    print("Dry run result:", res)
    
    # Since we are live, we can execute the actual mint, assuming sufficient ERG for box minimum!
    # Ensure you are on testnet or use real ERG.
    print("\nExecuting live mint...")
    toolkit._safety.dry_run = False
    
    try:
        live_res = toolkit.mint_token(
            name="AgentPyCoin",
            description="Agent Framework Minting Test",
            amount=100_000,
            decimals=0,
        )
        print("Live run result:", live_res)
        print("\nToken minted successfully!")
        print(f"Token ID: {live_res.get('token_id')}")
        print(f"Transaction ID: {live_res.get('tx_id')}")
        print(f"View transaction: https://testnet.ergoplatform.com/en/transactions/{live_res.get('tx_id')}")
    except Exception as e:
        print(f"Failed to mint token: {e}")

if __name__ == "__main__":
    asyncio.run(main())
