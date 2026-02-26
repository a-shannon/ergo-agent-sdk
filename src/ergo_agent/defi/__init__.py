"""
DeFi adapters for the Ergo Agent SDK.
"""
from .oracle import OracleReader
from .privacy_client import DepositSecret, WithdrawalProof
from .privacy_client import PrivacyPoolClient as PrivacyPoolClientV7
from .privacy_pool import PoolValidationError, PrivacyPoolClient
from .rosen import RosenBridge
from .sigmausd import SigmaUSD
from .spectrum import SpectrumDEX
from .treasury import ErgoTreasury

__all__ = [
    "DepositSecret",
    "ErgoTreasury",
    "OracleReader",
    "PoolValidationError",
    "PrivacyPoolClient",
    "PrivacyPoolClientV7",
    "RosenBridge",
    "SigmaUSD",
    "SpectrumDEX",
    "WithdrawalProof",
]

