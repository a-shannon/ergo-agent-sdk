from pydantic import BaseModel, Field


class DepositRequest(BaseModel):
    """Request model for creating a deposit transaction."""

    pool_box_id: str = Field(..., description="Box ID of the specific pool to deposit into")
    denomination: int = Field(..., description="Amount of tokens to deposit")
    stealth_key: str | None = Field(
        None,
        description="User's stealth public key (hex). Auto-generated if omitted.",
    )


class DepositResponse(BaseModel):
    """Response model for a successful deposit."""

    tx_id: str = Field(..., description="Transaction ID of the broadcasted deposit")
    stealth_key: str = Field(..., description="Stealth public key used in the deposit")
    secret_key: str | None = Field(
        None,
        description="Auto-generated secret key. KEEP THIS SAFE. Only returned if auto-generated.",
    )
    pool_box_id: str = Field(..., description="Box ID of the new pool state after this deposit")


class WithdrawRequest(BaseModel):
    """Request model for creating a withdrawal transaction."""

    secret_key: str = Field(..., description="User's 32-byte secret key (hex)")
    recipient_address: str = Field(
        ..., description="Standard Ergo address to receive the withdrawn funds"
    )
    pool_box_id: str | None = Field(
        None,
        description="Specific pool box to withdraw from. Automatically resolved if omitted.",
    )


class WithdrawResponse(BaseModel):
    """Response model for a successful withdrawal."""

    tx_id: str = Field(..., description="Transaction ID of the broadcasted withdrawal")
    key_image: str = Field(..., description="Key image (nullifier) used to prevent double-spends")
    new_pool_box_id: str = Field(..., description="Box ID of the new pool state")


class PoolStatusResponse(BaseModel):
    """Response model for active pool details."""

    pool_id: str = Field(..., description="Pool Box ID")
    token_id: str = Field(..., description="Token ID the pool operates on")
    denomination: int = Field(..., description="Standard denomination size of the pool")
    ring_size: int = Field(..., description="Current number of depositors in the pool")
    max_ring: int = Field(..., description="Maximum allowed depositors before exhaustion")
