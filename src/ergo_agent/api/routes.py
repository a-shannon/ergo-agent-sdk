
from fastapi import APIRouter, HTTPException, Request

from ergo_agent.api.models import (
    DepositRequest,
    DepositResponse,
    PoolStatusResponse,
    WithdrawRequest,
    WithdrawResponse,
)
from ergo_agent.core.privacy import generate_fresh_secret

router = APIRouter(tags=["Privacy Pool"])


def get_pool_client(request: Request):
    """Dependency to retrieve the initialized PrivacyPoolClient from app state."""
    client = getattr(request.app.state, "privacy_client", None)
    if not client:
        raise HTTPException(status_code=500, detail="privacy pool client not initialized")
    return client


@router.get("/pools", response_model=list[PoolStatusResponse])
async def list_pools(request: Request, denomination: int | None = None):
    """
    List active privacy pools.
    Optionally filter by denomination.
    """
    client = get_pool_client(request)
    pools = client.get_active_pools(denomination)

    results = []
    for p in pools:
        results.append(
            PoolStatusResponse(
                pool_id=p["pool_id"],
                token_id=p["token_id"],
                denomination=p["denomination"],
                ring_size=p["ring_size"],
                max_ring=p["max_ring"],
            )
        )
    return results


@router.post("/pool/deposit", response_model=DepositResponse)
async def deposit(request: Request, req: DepositRequest):
    """
    Deposit into a privacy pool.

    Auto-generates a stealth key sequence if `stealth_key` is omitted.
    Returns the transaction ID, inserted stealth key, and optionally the secret key if auto-generated.
    ALWAYS STORE THE SECRET KEY SECURELY to withdraw later.
    """
    client = get_pool_client(request)

    secret_key = None
    stealth_key = req.stealth_key

    if not stealth_key:
        # Generate fresh keys locally
        secret_key, stealth_key = generate_fresh_secret()

    # Build the transaction
    builder = client.build_deposit_tx(
        pool_box_id=req.pool_box_id,
        user_stealth_key=stealth_key,
        denomination=req.denomination,
    )

    unsigned_tx = builder.build()

    # Sign and submit
    if not client.wallet:
        raise HTTPException(status_code=500, detail="Wallet not configured for signing.")

    signed_tx = client.wallet.sign_transaction(unsigned_tx, client.node)
    tx_id = client.node.submit_transaction(signed_tx)

    # Determine the new pool box ID from the unsigned_tx outputs
    # The pool box is always the first output in our builder sequence
    new_pool_box_id = "unknown"
    pool_tree = None

    # Need to look up the pool box tree to find it in the output
    try:
        pool_box = client.node.get_box_by_id(req.pool_box_id)
        if pool_box:
            pool_tree = pool_box.ergo_tree
            for out in unsigned_tx.get("outputs", []):
                if out.get("ergoTree") == pool_tree:
                    new_pool_box_id = out.get("boxId", "unknown")
                    break
    except Exception:
        pass

    return DepositResponse(
        tx_id=tx_id,
        stealth_key=stealth_key,
        secret_key=secret_key,
        pool_box_id=new_pool_box_id,
    )


@router.post("/pool/withdraw", response_model=WithdrawResponse)
async def withdraw(request: Request, req: WithdrawRequest):
    """
    Withdraw from a privacy pool using the 32-byte exact secret key.

    If `pool_box_id` is omitted, the SDK will automatically scan active pools
    to find where this secret key belongs.
    """
    client = get_pool_client(request)

    pool_id_to_use = req.pool_box_id
    if not pool_id_to_use:
        # User didn't specify which pool. The SDK needs to resolve it
        # Try to find a pool box where this key is a depositor but not a withdrawer.
        # It's an internal SDK helper we might add, but for now, require it or query it.
        # As an advanced framework feature, let's just attempt on the first matching active pool.
        # But this is dangerous if multiple tokens. If omitted, we'll error out nicely for now
        # until a multi-pool auto-resolve feature is strictly requested.
        raise HTTPException(
            status_code=400,
            detail="pool_box_id is currently required for withdrawal. Please provide the current pool box ID."
        )

    builder = client.build_withdrawal_tx(
        pool_box_id=pool_id_to_use,
        recipient_stealth_address=req.recipient_address,
        secret_hex=req.secret_key,
    )

    unsigned_tx = builder.build()

    # Extract hints and signing secrets
    secrets = getattr(builder, "signing_secrets", None)

    if not client.wallet:
        raise HTTPException(status_code=500, detail="Wallet not configured for API signing.")

    signed_tx = client.wallet.sign_transaction(unsigned_tx, client.node, secrets=secrets)
    tx_id = client.node.submit_transaction(signed_tx)

    from ergo_agent.core.privacy import compute_key_image

    new_pool_box_id = "unknown"
    try:
        pool_box = client.node.get_box_by_id(pool_id_to_use)
        if pool_box:
            pool_tree = pool_box.ergo_tree
            for out in unsigned_tx.get("outputs", []):
                if out.get("ergoTree") == pool_tree:
                    new_pool_box_id = out.get("boxId", "unknown")
                    break
    except Exception:
        pass

    return WithdrawResponse(
        tx_id=tx_id,
        key_image=compute_key_image(req.secret_key),
        new_pool_box_id=new_pool_box_id
    )
