"""
DeFi adapters for the Ergo Agent SDK.
"""
from .oracle import OracleReader
from .rosen import RosenBridge
from .sigmausd import SigmaUSD
from .spectrum import SpectrumDEX

__all__ = ["OracleReader", "SpectrumDEX", "SigmaUSD", "RosenBridge"]
