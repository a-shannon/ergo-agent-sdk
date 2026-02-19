"""
ergo-agent: Open-source Python SDK for AI agents on the Ergo blockchain.

Usage:
    from ergo_agent import ErgoNode, Wallet
    from ergo_agent.tools import ErgoToolkit, SafetyConfig
"""

from ergo_agent.core.builder import TransactionBuilder
from ergo_agent.core.models import Box, Token, Transaction
from ergo_agent.core.node import ErgoNode
from ergo_agent.core.wallet import Wallet

__version__ = "0.1.0"
__all__ = [
    "ErgoNode",
    "Wallet",
    "TransactionBuilder",
    "Box",
    "Token",
    "Transaction",
]
