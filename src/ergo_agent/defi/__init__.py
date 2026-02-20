"""
DeFi adapters for the Ergo Agent SDK.
"""
from .oracle import OracleReader
from .spectrum import SpectrumDEX
from .sigmausd import SigmaUSD
from .rosen import RosenBridge

__all__ = ["OracleReader", "SpectrumDEX", "SigmaUSD", "RosenBridge"]
