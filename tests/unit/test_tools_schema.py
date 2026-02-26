"""Unit tests for OpenAI/Anthropic tool schema structure."""

from unittest.mock import MagicMock


def make_toolkit():
    """Build a toolkit with mocked dependencies."""
    from ergo_agent.tools.safety import SafetyConfig
    from ergo_agent.tools.toolkit import ErgoToolkit
    node = MagicMock()
    wallet = MagicMock()
    wallet.address = "9fXWbPTestAddress"
    wallet.read_only = True
    return ErgoToolkit(node=node, wallet=wallet, safety=SafetyConfig())


def test_openai_tools_format():
    toolkit = make_toolkit()
    tools = toolkit.to_openai_tools()
    assert isinstance(tools, list)
    assert len(tools) >= 5
    for tool in tools:
        assert tool["type"] == "function"
        assert "name" in tool["function"]
        assert "description" in tool["function"]
        assert "parameters" in tool["function"]


def test_anthropic_tools_format():
    toolkit = make_toolkit()
    tools = toolkit.to_anthropic_tools()
    assert isinstance(tools, list)
    assert len(tools) >= 5
    for tool in tools:
        assert "name" in tool
        assert "description" in tool
        assert "input_schema" in tool


def test_openai_tool_names():
    toolkit = make_toolkit()
    tools = toolkit.to_openai_tools()
    names = {t["function"]["name"] for t in tools}
    required = {
        "get_wallet_balance",
        "get_erg_price",
        "get_swap_quote",
        "send_funds",
        "privacy_pool_get_status",
        "privacy_pool_deposit",
        "privacy_pool_withdraw",
        "privacy_pool_export_view_key",
    }
    assert required.issubset(names)


def test_execute_tool_unknown():
    toolkit = make_toolkit()
    result = toolkit.execute_tool("nonexistent_tool", {})
    import json
    data = json.loads(result)
    assert "error" in data


def test_execute_tool_get_safety_status():
    toolkit = make_toolkit()
    result = toolkit.execute_tool("get_safety_status", {})
    import json
    data = json.loads(result)
    assert "dry_run" in data
    assert "daily_erg_spent" in data
