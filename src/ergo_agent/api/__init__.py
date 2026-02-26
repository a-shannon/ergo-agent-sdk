"""
API module for the Ergo Agent SDK.

Provides FastAPI routes and models for exposing SDK functionality as a REST API.
"""

from ergo_agent.api.models import (
    DepositRequest,
    DepositResponse,
    PoolStatusResponse,
    WithdrawRequest,
    WithdrawResponse,
)

__all__ = [
    "DepositRequest",
    "DepositResponse",
    "PoolStatusResponse",
    "WithdrawRequest",
    "WithdrawResponse",
]
