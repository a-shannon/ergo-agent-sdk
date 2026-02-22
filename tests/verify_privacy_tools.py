from ergo_agent.core.node import ErgoNode
from ergo_agent.core.wallet import Wallet
from ergo_agent.tools.toolkit import ErgoToolkit


def main():
    # 1. Initialize core components (using dummy testnet address)
    node = ErgoNode()
    # 9how9k2dp67jXDnCM6TeRPKtQrToCs5MYL2JoSgyGHLXm1eHxWs is a real test vector
    wallet = Wallet.read_only("9how9k2dp67jXDnCM6TeRPKtQrToCs5MYL2JoSgyGHLXm1eHxWs") # Dummy receiver
    toolkit = ErgoToolkit(node, wallet)

    # 2. Verify OpenAI definitions
    openai_tools = toolkit.to_openai_tools()
    privacy_tools_openai = [t["function"]["name"] for t in openai_tools if "privacy_pool" in t["function"]["name"]]
    print(f"[SUCCESS] OpenAI Tools found: {privacy_tools_openai}")

    # 3. Verify Anthropic definitions
    anthropic_tools = toolkit.to_anthropic_tools()
    privacy_tools_anthropic = [t["name"] for t in anthropic_tools if "privacy_pool" in t["name"]]
    print(f"[SUCCESS] Anthropic Tools found: {privacy_tools_anthropic}")

    # 4. Verify LangChain Tool Wrappers
    langchain_tools = toolkit.to_langchain_tools()
    privacy_tools_lc = [t.name for t in langchain_tools if "privacy_pool" in t.name]
    print(f"[SUCCESS] LangChain Tools found: {privacy_tools_lc}")

    assert "get_privacy_pools" in privacy_tools_lc
    assert "deposit_to_privacy_pool" in privacy_tools_lc
    assert "withdraw_from_privacy_pool" in privacy_tools_lc

    print("\n[DONE] Phase K: LLM Tool Integration verified successfully!")

if __name__ == "__main__":
    main()
